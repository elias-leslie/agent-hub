"""Tests for runtime context APIs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.prompt import Prompt
from app.services.memory.budget import BudgetUsage
from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.memory_models import MemoryApplicability
from app.services.memory.service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    RuntimeContextBlockResponse,
    RuntimeContextOverrideResponse,
    RuntimeContextPreviewResponse,
    _build_canonical_blocks,
    _build_memory_blocks,
    _build_prompt_blocks,
    _default_prompt_position,
    _filter_live_override_items,
    _forced_memory_item_matches,
    _render_blocks,
    _resolve_canonical_project_id,
    _resolve_overrides,
    _ResolvedOverride,
    _RuntimeContextSelection,
    apply_runtime_memory_overrides_to_context,
    build_canonical_context_delivery,
)


@pytest.mark.asyncio
async def test_canonical_project_resolution_uses_longest_registered_root() -> None:
    request = CanonicalContextDeliveryRequest(
        consumer_surface="codex",
        cwd="/srv/workspaces/projects/agent-hub/backend/app",
    )
    roots = {
        "workspace": "/srv/workspaces/projects",
        "agent-hub": "/srv/workspaces/projects/agent-hub",
    }

    with patch(
        "app.core.project_roots.get_registered_project_roots",
        new=AsyncMock(return_value=roots),
    ):
        resolved = await _resolve_canonical_project_id(request)

    assert resolved == "agent-hub"


@pytest.mark.asyncio
async def test_canonical_project_resolution_does_not_infer_repo_basename() -> None:
    request = CanonicalContextDeliveryRequest(
        consumer_surface="codex",
        repo_root="/tmp/aliases/agent-hub",
    )

    with patch(
        "app.core.project_roots.get_registered_project_roots",
        new=AsyncMock(
            return_value={"agent-hub": "/srv/workspaces/projects/agent-hub"}
        ),
    ):
        resolved = await _resolve_canonical_project_id(request)

    assert resolved is None


@pytest.mark.asyncio
async def test_canonical_project_resolution_rejects_explicit_unregistered_id() -> None:
    request = CanonicalContextDeliveryRequest(
        consumer_surface="codex",
        project_id="not-registered",
    )

    with (
        patch(
            "app.core.project_roots.get_registered_project_roots",
            new=AsyncMock(return_value={"agent-hub": "/srv/workspaces/projects/agent-hub"}),
        ),
        pytest.raises(ValueError, match="Unknown project_id"),
    ):
        await _resolve_canonical_project_id(request)


def _override(**overrides):
    row = SimpleNamespace(
        id="override-1",
        consumer_profile="codex_startup",
        project_id=None,
        source_type="memory",
        source_id="memory-1",
        mode="order",
        position=50,
        enabled=True,
        note=None,
        tier_override=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_resolve_overrides_prefers_project_layer_over_global() -> None:
    rows = [
        _override(id="project", project_id="summitflow", source_id="mem-1", position=90),
        _override(id="global", project_id=None, source_id="mem-1", position=10),
    ]

    resolved = _resolve_overrides(rows)

    assert len(resolved) == 1
    assert resolved[0].id == "project"
    assert resolved[0].position == 90


def _memory_result(
    source_id: str,
    *,
    content: str,
    category: MemoryCategory,
) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=source_id,
        content=content,
        summary=content,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        facts=[],
        category=category,
    )


def test_forced_memory_include_cannot_bypass_scope_or_applicability() -> None:
    item = _memory_result(
        "forced-memory",
        content="Project-specific instruction",
        category=MemoryCategory.REFERENCE,
    )
    item.scope = MemoryScope.PROJECT
    item.scope_id = "summitflow"
    item.applicability = MemoryApplicability(consumer_surfaces=["codex"])

    def matches(project_id: str, consumer_surface: str) -> bool:
        return _forced_memory_item_matches(
            item,
            project_id=project_id,
            include_global=True,
            include_mandates=True,
            include_guardrails=True,
            include_references=True,
            exclude_tags=[],
            exclude_memory_uuids=[],
            consumer_surface=consumer_surface,
            consumer_profile="agent_startup",
            consumer_agent_slug=None,
            consumer_tags=[],
        )

    assert not matches("agent-hub", "codex")
    item.scope_id = "agent-hub"
    assert not matches("agent-hub", "pi")
    assert matches("agent-hub", "codex")


@pytest.mark.asyncio
async def test_canonical_memory_selection_is_uncapped_and_required_policy_is_full() -> None:
    mandate = _memory_result(
        "memory-mandate",
        content="Full required policy text that must never be summarized.",
        category=MemoryCategory.MANDATE,
    )
    mandate.compact_content = "Lossy summary"
    mandate.render_mode = "summary"
    context = ProgressiveContext(mandates=[mandate])
    build_context = AsyncMock(return_value=context)

    with (
        patch(
            "app.services.runtime_context.build_progressive_context",
            build_context,
        ),
        patch(
            "app.services.runtime_context._load_memory_source_revisions",
            new=AsyncMock(return_value={}),
        ),
    ):
        blocks = await _build_memory_blocks(
            AsyncMock(),
            consumer_profile="agent_startup",
            consumer_surface="codex",
            agent_slug=None,
            consumer_tags=[],
            project_id=None,
            query="startup",
            task_type=None,
            phase=None,
            include_global=True,
            include_mandates=True,
            include_guardrails=True,
            include_references=True,
            include_reference_index=True,
            exclude_tags=[],
            exclude_memory_uuids=[],
            variant=None,
            overrides=[],
            override_by_key={},
            excluded=set(),
        )

    await_args = build_context.await_args
    assert await_args is not None
    assert await_args.kwargs["preserve_required_policy"] is True
    assert await_args.kwargs["consumer_surface"] == "codex"
    assert blocks[0].content == mandate.content
    assert blocks[0].render_tier == "L2"


@pytest.mark.asyncio
async def test_apply_runtime_memory_overrides_to_context_excludes_and_includes() -> None:
    keep = _memory_result(
        "memory-keep",
        content="Keep this mandate.",
        category=MemoryCategory.MANDATE,
    )
    drop = _memory_result(
        "memory-drop",
        content="Drop this mandate.",
        category=MemoryCategory.MANDATE,
    )
    forced = _memory_result(
        "memory-forced",
        content="Forced guardrail.",
        category=MemoryCategory.GUARDRAIL,
    )
    context = ProgressiveContext(
        mandates=[keep, drop],
        budget_usage=BudgetUsage(),
        total_tokens=999,
        debug_info={"total_tokens": 999},
    )
    rows = [
        _override(source_id="memory-drop", mode="exclude", position=10),
        _override(
            source_id="memory-forced",
            mode="include",
            position=5,
            tier_override="L0",
        ),
    ]

    async def _same_rows(_db, loaded_rows):
        return loaded_rows

    with (
        patch(
            "app.services.runtime_context._load_override_rows",
            new=AsyncMock(return_value=rows),
        ) as load_rows,
        patch(
            "app.services.runtime_context._filter_live_override_rows",
            new=AsyncMock(side_effect=_same_rows),
        ),
        patch(
            "app.services.runtime_context._fetch_forced_memory_items",
            new=AsyncMock(return_value=[forced]),
        ) as fetch_forced,
    ):
        await apply_runtime_memory_overrides_to_context(
            AsyncMock(),
            consumer_profile="agent_startup",
            project_id="afterlife",
            query="startup context",
            context=context,
        )

    assert [item.uuid for item in context.mandates] == ["memory-keep"]
    assert [item.uuid for item in context.guardrails] == ["memory-forced"]
    assert context.guardrails[0].render_reason == "user_override"
    assert context.total_tokens != 999
    assert context.debug_info["mandates_count"] == 1
    assert context.debug_info["guardrails_count"] == 1
    assert context.debug_info["runtime_context_overrides_applied"] is True
    load_rows.assert_awaited_once()
    fetch_forced.assert_awaited_once()


def test_render_blocks_groups_memory_lines() -> None:
    rendered = _render_blocks(
        [
            RuntimeContextBlockResponse(
                id="prompt:agentic-cli-startup-core",
                source_type="prompt",
                source_id="agentic-cli-startup-core",
                title="Agentic CLI Startup Core",
                content="Direct concise.",
                token_count=2,
                origin="override",
                mode="include",
                position=10,
            ),
            RuntimeContextBlockResponse(
                id="memory:12345678-aaaa-bbbb-cccc-123456789abc",
                source_type="memory",
                source_id="12345678-aaaa-bbbb-cccc-123456789abc",
                title="Use st",
                content="**Use st**: Use st for dev work.",
                token_count=8,
                origin="auto",
                mode="order",
                position=100,
                tier="mandate",
            ),
        ]
    )

    assert "## Agentic CLI Startup Core\nDirect concise." in rendered
    assert "## Runtime Memory" in rendered
    assert "[M:12345678] **Use st**: Use st for dev work." in rendered


def test_render_blocks_skips_excluded() -> None:
    rendered = _render_blocks(
        [
            RuntimeContextBlockResponse(
                id="prompt:keep",
                source_type="prompt",
                source_id="keep",
                title="Keep",
                content="kept content",
                token_count=2,
                origin="auto",
                mode="order",
                position=10,
            ),
            RuntimeContextBlockResponse(
                id="prompt:drop",
                source_type="prompt",
                source_id="drop",
                title="Drop",
                content="dropped content",
                token_count=2,
                origin="auto",
                mode="exclude",
                position=20,
            ),
        ]
    )

    assert "kept content" in rendered
    assert "dropped content" not in rendered


@pytest.mark.asyncio
async def test_canonical_delivery_has_stable_hash_order_and_provenance() -> None:
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=None,
        query="fix context",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:startup",
                source_type="prompt",
                source_id="startup",
                title="Startup",
                content="Preserve native instructions.",
                token_count=4,
                origin="auto",
                mode="order",
                position=100,
                source_revision="sha256:prompt-revision",
            ),
            RuntimeContextBlockResponse(
                id="memory:12345678-aaaa-bbbb-cccc-123456789abc",
                source_type="memory",
                source_id="12345678-aaaa-bbbb-cccc-123456789abc",
                title="Canonical memory",
                content="Use Agent Hub context.",
                token_count=4,
                origin="auto",
                mode="order",
                position=1000,
                tier="mandate",
                source_revision="v3:sha256:memory-revision",
                review_status="clean",
                sensitivity_tier="normal",
            ),
        ],
        excluded=[],
        overrides=[],
        project_index="<project-index>global</project-index>",
        tool_capabilities="<tools>st</tools>",
        budget_tokens=3500,
        budget_enabled=False,
    )
    request = CanonicalContextDeliveryRequest(
        consumer_surface="codex",
        task="fix context",
        session_id="session-1",
        capabilities=["developer_context"],
    )

    with patch(
        "app.services.runtime_context._select_runtime_context",
        new=AsyncMock(return_value=selection),
    ):
        response = await build_canonical_context_delivery(AsyncMock(), request)

    assert response.status == "ok"
    assert response.delivery_mode == "additive"
    assert response.native_context_policy == "preserve"
    assert response.payload_hash == hashlib.sha256(response.rendered.encode()).hexdigest()
    assert [block.provenance.source_id for block in response.blocks] == [
        "12345678-aaaa-bbbb-cccc-123456789abc",
        "startup",
        "project-index:global",
        "tool-capabilities:agent_startup:global",
    ]
    assert response.blocks[0].provenance.source_revision == "v3:sha256:memory-revision"
    assert response.blocks[1].provenance.source_revision == "sha256:prompt-revision"
    assert response.required_policy.state == "complete"
    assert response.required_policy.missing_source_ids == []
    assert response.metadata.query_hash == hashlib.sha256(b"fix context").hexdigest()


@pytest.mark.asyncio
async def test_canonical_delivery_budget_is_telemetry_not_a_payload_ceiling() -> None:
    required_content = "Required policy sentence. " * 2_000
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=None,
        query="startup",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:required-policy",
                source_type="prompt",
                source_id="required-policy",
                title="Required Policy",
                content=required_content,
                token_count=1,
                origin="auto",
                mode="order",
                position=100,
                prompt_type="global_mandate",
            )
        ],
        excluded=[],
        overrides=[],
        project_index="",
        tool_capabilities="",
        budget_tokens=1,
        budget_enabled=True,
    )

    with patch(
        "app.services.runtime_context._select_runtime_context",
        new=AsyncMock(return_value=selection),
    ):
        response = await build_canonical_context_delivery(
            AsyncMock(),
            CanonicalContextDeliveryRequest(consumer_surface="codex"),
        )

    assert response.status == "ok"
    assert response.preview is not None
    assert response.preview.budget_enabled is True
    assert response.preview.budget_tokens == 1
    assert response.estimated_tokens > response.preview.budget_tokens
    assert response.blocks[0].content == required_content
    assert required_content.strip() in response.rendered


@pytest.mark.asyncio
async def test_canonical_delivery_fails_closed_when_required_context_errors() -> None:
    request = CanonicalContextDeliveryRequest(consumer_surface="claude_code")
    with patch(
        "app.services.runtime_context._select_runtime_context",
        new=AsyncMock(side_effect=RuntimeError("policy database unavailable")),
    ):
        response = await build_canonical_context_delivery(AsyncMock(), request)

    assert response.status == "failed"
    assert response.required_policy.state == "failed"
    assert response.blocks == []
    assert "supplemental context is unavailable and was not injected" in response.rendered
    assert "consumer must apply its configured failure policy" in response.rendered
    assert response.payload_hash == hashlib.sha256(response.rendered.encode()).hexdigest()


@pytest.mark.asyncio
async def test_canonical_delivery_fails_when_applicable_required_policy_is_missing() -> None:
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=None,
        query="startup",
        blocks=[],
        excluded=[],
        overrides=[],
        project_index="",
        tool_capabilities="",
        budget_tokens=0,
        budget_enabled=False,
        expected_required_source_ids=["required-mandate"],
    )
    with patch(
        "app.services.runtime_context._select_runtime_context",
        new=AsyncMock(return_value=selection),
    ):
        response = await build_canonical_context_delivery(
            AsyncMock(),
            CanonicalContextDeliveryRequest(consumer_surface="codex"),
        )

    assert response.status == "failed"
    assert response.required_policy.required_source_ids == ["required-mandate"]
    assert response.required_policy.missing_source_ids == ["required-mandate"]
    assert response.failure is not None
    assert response.failure.error_type == "CanonicalRequiredPolicyIncomplete"


@pytest.mark.asyncio
async def test_filter_live_override_items_drops_missing_sources() -> None:
    live_memory_id = uuid.uuid4()
    missing_memory_id = uuid.uuid4()
    rows = [
        _override(id="live-memory", source_id=str(live_memory_id)),
        _override(id="missing-memory", source_id=str(missing_memory_id)),
        _override(id="live-prompt", source_type="prompt", source_id="live-prompt"),
        _override(
            id="missing-prompt",
            source_type="prompt",
            source_id="missing-prompt",
        ),
    ]
    prompt_result = MagicMock()
    prompt_result.scalars.return_value.all.return_value = ["live-prompt"]
    memory_result = MagicMock()
    memory_result.scalars.return_value.all.return_value = [live_memory_id]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[prompt_result, memory_result])

    filtered = await _filter_live_override_items(db, rows)

    assert [item.id for item in filtered] == ["live-memory", "live-prompt"]


def test_default_prompt_position_orders_by_authority_not_insertion_id() -> None:
    guardrail = SimpleNamespace(id=99, prompt_type="global_guardrail")
    mandate = SimpleNamespace(id=1, prompt_type="global_mandate")
    standard_old = SimpleNamespace(id=2, prompt_type="standard")
    standard_new = SimpleNamespace(id=200, prompt_type="standard")

    assert _default_prompt_position(guardrail) < _default_prompt_position(mandate)
    assert _default_prompt_position(mandate) < _default_prompt_position(standard_old)
    assert _default_prompt_position(standard_old) == _default_prompt_position(standard_new)
    assert _default_prompt_position(standard_new) < 1000


def _make_prompt_row(
    slug: str,
    *,
    boot_eligible: bool,
    is_global: bool = True,
    prompt_type: str = "standard",
    name: str = "P",
    row_id: int = 1,
    owner_agent_id: int | None = None,
) -> Prompt:
    prompt = Prompt(
        slug=slug,
        name=name,
        content=f"prompt body for {slug}",
        description=None,
        is_global=is_global,
        enabled=True,
        boot_eligible=boot_eligible,
        exclude_agents=[],
    )
    prompt.id = row_id
    prompt.prompt_type = prompt_type
    prompt.owner_agent_id = owner_agent_id
    return prompt


def _mock_db_returning(rows: list[Prompt]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_build_prompt_blocks_auto_includes_enabled_global_prompt() -> None:
    db = _mock_db_returning([_make_prompt_row("auto-prompt", boot_eligible=False)])
    blocks = await _build_prompt_blocks(db, overrides=[], override_by_key={}, excluded=set())
    assert len(blocks) == 1
    assert blocks[0].source == "auto"
    assert blocks[0].auto_reason == "global"
    assert blocks[0].mode == "order"


@pytest.mark.asyncio
async def test_build_prompt_blocks_orders_authority_then_slug_independent_of_ids() -> None:
    db = _mock_db_returning(
        [
            _make_prompt_row(
                "z-standard",
                boot_eligible=False,
                prompt_type="standard",
                row_id=1,
            ),
            _make_prompt_row(
                "z-mandate",
                boot_eligible=False,
                prompt_type="global_mandate",
                row_id=900,
            ),
            _make_prompt_row(
                "z-guardrail",
                boot_eligible=False,
                prompt_type="global_guardrail",
                row_id=500,
            ),
            _make_prompt_row(
                "a-mandate",
                boot_eligible=False,
                prompt_type="global_mandate",
                row_id=999,
            ),
        ]
    )

    blocks = await _build_prompt_blocks(
        db,
        overrides=[],
        override_by_key={},
        excluded=set(),
    )

    assert [block.source_id for block in blocks] == [
        "z-guardrail",
        "a-mandate",
        "z-mandate",
        "z-standard",
    ]


def test_canonical_prompt_blocks_preserve_prompt_type_authority() -> None:
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=None,
        query="startup",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:safety",
                source_type="prompt",
                source_id="safety",
                title="Safety",
                content="Stay safe.",
                token_count=2,
                origin="auto",
                mode="order",
                position=100,
                prompt_type="global_guardrail",
            ),
            RuntimeContextBlockResponse(
                id="prompt:routine",
                source_type="prompt",
                source_id="routine",
                title="Routine",
                content="Follow routine.",
                token_count=2,
                origin="auto",
                mode="order",
                position=200,
                prompt_type="global_mandate",
            ),
        ],
        excluded=[],
        overrides=[],
        project_index="",
        tool_capabilities="",
        budget_tokens=0,
        budget_enabled=False,
    )

    blocks = _build_canonical_blocks(selection, "")

    assert [(block.kind, block.authority) for block in blocks] == [
        ("global_guardrail", "operator_guardrail"),
        ("global_mandate", "operator_mandate"),
    ]


def test_delivery_authority_rank_overrides_manual_positions_and_advisory_blocks() -> None:
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id="agent-hub",
        query="startup",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:project-policy",
                source_type="prompt",
                source_id="project-policy",
                title="Project Policy",
                content="Project instruction.",
                token_count=2,
                origin="override",
                source="pinned",
                mode="include",
                position=1,
                prompt_type="standard",
            ),
            RuntimeContextBlockResponse(
                id="memory:mandate",
                source_type="memory",
                source_id="mandate",
                title="Mandate",
                content="Required mandate.",
                token_count=2,
                origin="auto",
                mode="order",
                position=5000,
                tier="mandate",
            ),
            RuntimeContextBlockResponse(
                id="prompt:safety",
                source_type="prompt",
                source_id="safety",
                title="Safety",
                content="Safety guardrail.",
                token_count=2,
                origin="auto",
                mode="order",
                position=9000,
                prompt_type="global_guardrail",
            ),
        ],
        excluded=[],
        overrides=[],
        project_index="project index",
        tool_capabilities="tool reference",
        budget_tokens=0,
        budget_enabled=False,
    )

    blocks = _build_canonical_blocks(selection, "recent continuity")

    assert [block.provenance.source_id for block in blocks] == [
        "safety",
        "mandate",
        "project-policy",
        "project-index:agent-hub",
        "continuity:agent-hub",
        "tool-capabilities:agent_startup:agent-hub",
    ]


@pytest.mark.asyncio
async def test_build_prompt_blocks_does_not_auto_include_non_global_boot_prompt() -> None:
    db = _mock_db_returning(
        [_make_prompt_row("agent-prompt", boot_eligible=True, is_global=False)]
    )

    blocks = await _build_prompt_blocks(
        db,
        overrides=[],
        override_by_key={},
        excluded=set(),
    )

    assert blocks == []


@pytest.mark.asyncio
async def test_build_prompt_blocks_leaves_agent_owned_system_prompt_to_agent_stack() -> None:
    """Canonical shared context must not inject an assigned prompt a second time."""
    db = _mock_db_returning(
        [
            _make_prompt_row(
                "persona-system-prompt",
                boot_eligible=True,
                is_global=False,
                prompt_type="agent_system",
                owner_agent_id=9,
            )
        ]
    )

    blocks = await _build_prompt_blocks(
        db,
        overrides=[],
        override_by_key={},
        excluded=set(),
        agent_slug="persona",
    )

    assert blocks == []


@pytest.mark.asyncio
async def test_build_prompt_blocks_pin_marks_pinned() -> None:
    pinned = _make_prompt_row(
        "pinned-prompt",
        boot_eligible=False,
        is_global=False,
        row_id=2,
    )
    db = _mock_db_returning([pinned])
    override = _ResolvedOverride(
        source_type="prompt",
        source_id="pinned-prompt",
        mode="include",
        position=42,
        enabled=True,
        note=None,
        project_id="agent-hub",
        id="ov-1",
    )
    blocks = await _build_prompt_blocks(
        db,
        overrides=[override],
        override_by_key={("prompt", "pinned-prompt"): override},
        excluded=set(),
    )
    assert len(blocks) == 1
    assert blocks[0].source == "pinned"
    assert blocks[0].auto_reason is None
    assert blocks[0].position == 42
    assert blocks[0].mode == "include"
    assert blocks[0].scope == "project"
    assert blocks[0].scope_id == "agent-hub"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_agent_id", "project_id"),
    [(42, "agent-hub"), (None, None)],
)
async def test_build_prompt_blocks_rejects_unsafe_non_global_pins(
    owner_agent_id: int | None,
    project_id: str | None,
) -> None:
    pinned = _make_prompt_row(
        "unsafe-prompt",
        boot_eligible=False,
        is_global=False,
        owner_agent_id=owner_agent_id,
    )
    override = _ResolvedOverride(
        source_type="prompt",
        source_id="unsafe-prompt",
        mode="include",
        position=42,
        enabled=True,
        note=None,
        project_id=project_id,
        id="ov-unsafe",
    )

    blocks = await _build_prompt_blocks(
        _mock_db_returning([pinned]),
        overrides=[override],
        override_by_key={("prompt", "unsafe-prompt"): override},
        excluded=set(),
    )

    assert blocks == []


@pytest.mark.asyncio
async def test_build_prompt_blocks_exclude_overrides_pin() -> None:
    boot = _make_prompt_row("auto-prompt", boot_eligible=True, row_id=3)
    db = _mock_db_returning([boot])
    override = _ResolvedOverride(
        source_type="prompt",
        source_id="auto-prompt",
        mode="exclude",
        position=10,
        enabled=True,
        note=None,
        project_id=None,
        id="ov-x",
    )
    blocks = await _build_prompt_blocks(
        db,
        overrides=[override],
        override_by_key={("prompt", "auto-prompt"): override},
        excluded={("prompt", "auto-prompt")},
    )
    assert len(blocks) == 1
    # Excluded global prompts are still emitted as exclude-mode blocks
    # so the UI can show & restore them.
    assert blocks[0].mode == "exclude"


@pytest.mark.asyncio
async def test_profiles_endpoint_lists_agentic_cli_profiles(api_client) -> None:
    response = api_client.get("/api/runtime-context/profiles")

    assert response.status_code == 200
    profiles = [item["consumer_profile"] for item in response.json()["profiles"]]
    assert "agent_startup" in profiles


@pytest.mark.asyncio
async def test_delivery_endpoint_returns_authenticated_canonical_contract(api_client) -> None:
    selection = _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=None,
        query="startup context",
        blocks=[],
        excluded=[],
        overrides=[],
        project_index="",
        tool_capabilities="",
        budget_tokens=3500,
        budget_enabled=False,
    )
    with patch(
        "app.services.runtime_context._select_runtime_context",
        new=AsyncMock(return_value=selection),
    ):
        response = api_client.post(
            "/api/runtime-context/deliver",
            json={
                "consumer_surface": "pi",
                "session_id": "pi-session",
                "client_metadata": {"hook_event_name": "before_agent_start"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "agent-hub.context.v1"
    assert body["status"] == "ok"
    assert body["recommended_role"] == "developer"
    assert body["metadata"]["consumer_surface"] == "pi"
    assert body["metadata"]["session_id"] == "pi-session"
    assert body["metadata"]["client_metadata"]["hook_event_name"] == "before_agent_start"


def test_runtime_context_requires_internal_dashboard(test_client) -> None:
    response = test_client.get("/api/runtime-context/profiles")

    assert response.status_code == 403
    assert response.json()["error"] == "internal_only"


@pytest.mark.asyncio
async def test_overrides_endpoint_returns_layer_specific_rows(api_client) -> None:
    override = RuntimeContextOverrideResponse(
        id="override-1",
        consumer_profile="codex_startup",
        project_id="summitflow",
        source_type="memory",
        source_id="memory-1",
        mode="exclude",
        position=20,
        enabled=True,
        note=None,
    )
    mock_list = AsyncMock(return_value=[override])

    with patch("app.api.runtime_context.list_runtime_context_overrides", mock_list):
        response = api_client.get(
            "/api/runtime-context/codex_startup/overrides?project_id=summitflow"
        )

    assert response.status_code == 200
    assert response.json()["overrides"][0]["mode"] == "exclude"
    mock_list.assert_awaited_once()
    await_args = mock_list.await_args
    assert await_args is not None
    assert await_args.kwargs["project_id"] == "summitflow"


@pytest.mark.asyncio
async def test_preview_endpoint_returns_rendered_context(api_client) -> None:
    preview = RuntimeContextPreviewResponse(
        consumer_profile="codex_startup",
        project_id="summitflow",
        query="startup context",
        total_tokens=12,
        budget_tokens=3500,
        budget_enabled=True,
        rendered="## Agentic CLI Startup Core\nDirect concise.",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:agentic-cli-startup-core",
                source_type="prompt",
                source_id="agentic-cli-startup-core",
                title="Agentic CLI Startup Core",
                content="Direct concise.",
                token_count=2,
                origin="override",
                source="pinned",
                auto_reason=None,
                mode="include",
                position=10,
                scope="global",
                tags=["runtime_context"],
            )
        ],
        excluded=[
            RuntimeContextBlockResponse(
                id="memory:dropped",
                source_type="memory",
                source_id="dropped-uuid",
                title="Dropped memory",
                content="ignored",
                token_count=1,
                origin="auto",
                source="auto",
                auto_reason="tier:reference",
                mode="exclude",
                position=4000,
                tier="reference",
                scope="global",
            )
        ],
        overrides=[],
    )
    mock_render = AsyncMock(return_value=preview)

    with patch("app.api.runtime_context.render_runtime_context", mock_render):
        response = api_client.get(
            "/api/runtime-context/codex_startup/preview?project_id=summitflow"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens"] == 12
    assert body["budget_tokens"] == 3500
    assert body["budget_enabled"] is True
    assert body["blocks"][0]["source_id"] == "agentic-cli-startup-core"
    assert body["blocks"][0]["source"] == "pinned"
    assert body["blocks"][0]["scope"] == "global"
    assert body["excluded"][0]["source_id"] == "dropped-uuid"
    mock_render.assert_awaited_once()
