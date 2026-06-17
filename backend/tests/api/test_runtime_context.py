"""Tests for runtime context APIs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.prompt import Prompt
from app.services.memory.budget import BudgetUsage
from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.service import MemoryCategory, MemorySearchResult, MemorySource
from app.services.runtime_context import (
    RuntimeContextBlockResponse,
    RuntimeContextOverrideResponse,
    RuntimeContextPreviewResponse,
    _build_prompt_blocks,
    _default_prompt_position,
    _filter_live_override_items,
    _render_blocks,
    _resolve_overrides,
    _ResolvedOverride,
    apply_runtime_memory_overrides_to_context,
)


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


def test_default_prompt_position_orders_by_id() -> None:
    a = SimpleNamespace(id=1)
    b = SimpleNamespace(id=10)
    assert _default_prompt_position(a) < _default_prompt_position(b)  # type: ignore[arg-type]
    # Prompts must come before mandate-tier memories (base 1000).
    assert _default_prompt_position(b) < 1000  # type: ignore[arg-type]


def _make_prompt_row(slug: str, *, boot_eligible: bool, name: str = "P", row_id: int = 1) -> Prompt:
    prompt = Prompt(
        slug=slug,
        name=name,
        content=f"prompt body for {slug}",
        description=None,
        is_global=True,
        enabled=True,
        boot_eligible=boot_eligible,
        exclude_agents=[],
    )
    prompt.id = row_id
    prompt.prompt_type = "standard"
    return prompt


def _mock_db_returning(rows: list[Prompt]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_build_prompt_blocks_auto_includes_boot_eligible() -> None:
    db = _mock_db_returning([_make_prompt_row("auto-prompt", boot_eligible=True)])
    blocks = await _build_prompt_blocks(db, overrides=[], override_by_key={}, excluded=set())
    assert len(blocks) == 1
    assert blocks[0].source == "auto"
    assert blocks[0].auto_reason == "boot_eligible"
    assert blocks[0].mode == "order"


@pytest.mark.asyncio
async def test_build_prompt_blocks_pin_marks_pinned() -> None:
    pinned = _make_prompt_row("pinned-prompt", boot_eligible=False, row_id=2)
    db = _mock_db_returning([pinned])
    override = _ResolvedOverride(
        source_type="prompt",
        source_id="pinned-prompt",
        mode="include",
        position=42,
        enabled=True,
        note=None,
        project_id=None,
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
    # Excluded boot-eligible prompts are still emitted as exclude-mode blocks
    # so the UI can show & restore them.
    assert blocks[0].mode == "exclude"


@pytest.mark.asyncio
async def test_profiles_endpoint_lists_agentic_cli_profiles(api_client) -> None:
    response = api_client.get("/api/runtime-context/profiles")

    assert response.status_code == 200
    profiles = [item["consumer_profile"] for item in response.json()["profiles"]]
    assert "agent_startup" in profiles


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
