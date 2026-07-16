from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_dto import AgentDTO
from app.services.owned_prompt_service import (
    AGENT_SYSTEM_PROMPT_TYPE,
)
from app.services.runtime_prompt_stack import (
    RuntimePromptSection,
    collect_runtime_prompt_sections,
    dedupe_runtime_prompt_sections,
)


@pytest.fixture(autouse=True)
def _default_to_no_unassigned_owned_prompt():
    """Most fixtures model genuinely unmigrated agents unless stated otherwise."""
    with patch(
        "app.services.runtime_prompt_stack.get_owned_prompt",
        new=AsyncMock(return_value=None),
    ):
        yield


def _agent(*, slug: str = "note-titler", system_prompt: str = "Title notes tersely.") -> AgentDTO:
    return AgentDTO(
        id=1,
        slug=slug,
        name="Note Titler",
        description=None,
        system_prompt=system_prompt,
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.1,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_adds_agent_system_prompt_when_unassigned() -> None:
    agent = _agent()

    with patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[]),
        ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert len(sections) == 1
    assert sections[0].source_kind == "agent_system_prompt"
    assert sections[0].content == "<agent_persona>\nTitle notes tersely.\n</agent_persona>"


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_avoids_duplicate_fallback_when_owned_prompt_exists() -> None:
    agent = _agent()
    assignment = SimpleNamespace(
        role="system",
        priority=0,
        prompt=SimpleNamespace(
            enabled=True,
            is_global=False,
            prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
            name="Note Titler System Prompt",
            slug="note-titler-system-prompt",
            content="<agent_persona>\nCanonical prompt\n</agent_persona>",
            updated_at=None,
        ),
    )

    with patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[assignment]),
        ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert len(sections) == 1
    assert sections[0].source_kind == "agent_system_prompt"
    assert sections[0].source_id == "note-titler-system-prompt"
    assert "Canonical prompt" in sections[0].content


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_respects_disabled_owned_prompt() -> None:
    agent = _agent(system_prompt="Legacy compatibility mirror must stay disabled.")
    assignment = SimpleNamespace(
        role="system",
        priority=0,
        prompt=SimpleNamespace(
            enabled=False,
            is_global=False,
            prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
            name="Note Titler System Prompt",
            slug="note-titler-system-prompt",
            content="Disabled canonical prompt",
            updated_at=None,
        ),
    )

    with patch(
        "app.services.runtime_prompt_stack.get_agent_prompts",
        new=AsyncMock(return_value=[assignment]),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert sections == []


@pytest.mark.asyncio
async def test_disabled_owned_prompt_without_assignment_still_suppresses_mirror() -> None:
    agent = _agent(system_prompt="Raw ORM compatibility mirror must stay disabled.")
    disabled_owned_prompt = SimpleNamespace(
        enabled=False,
        name="Note Titler System Prompt",
        slug="note-titler-system-prompt",
        content="Disabled canonical prompt",
        updated_at=None,
    )

    with (
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.runtime_prompt_stack.get_owned_prompt",
            new=AsyncMock(return_value=disabled_owned_prompt),
        ),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert sections == []


@pytest.mark.asyncio
async def test_enabled_owned_prompt_without_assignment_renders_canonical_row() -> None:
    agent = _agent(system_prompt="Stale raw ORM compatibility mirror.")
    enabled_owned_prompt = SimpleNamespace(
        enabled=True,
        name="Note Titler System Prompt",
        slug="note-titler-system-prompt",
        content="Canonical unassigned owned prompt",
        updated_at=None,
    )

    with (
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.runtime_prompt_stack.get_owned_prompt",
            new=AsyncMock(return_value=enabled_owned_prompt),
        ),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert len(sections) == 1
    assert sections[0].source_id == "note-titler-system-prompt"
    assert sections[0].content == "Canonical unassigned owned prompt"
    assert "Stale raw ORM" not in sections[0].content


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_skips_global_prompt_assignment() -> None:
    agent = _agent()
    assignment = SimpleNamespace(
        role="system",
        priority=0,
        prompt=SimpleNamespace(
            enabled=True,
            is_global=True,
            prompt_type="standard",
            name="Platform Context",
            slug="platform-context",
            content="Canonical global prompt",
            updated_at=None,
        ),
    )

    with patch(
        "app.services.runtime_prompt_stack.get_agent_prompts",
        new=AsyncMock(return_value=[assignment]),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_global_prompts=False,
            include_persona_context=False,
        )

    assert [section.source_id for section in sections] == ["note-titler"]


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_delegates_global_selection_to_canonical() -> None:
    agent = _agent()
    delivery = SimpleNamespace(
        status="ok",
        delivery_id="delivery",
        rendered="CONTEXT",
        blocks=[
            SimpleNamespace(
                title="Platform Context",
                content="CONTEXT",
                provenance=SimpleNamespace(
                    source_type="prompt",
                    source_id="platform-context",
                ),
            )
        ],
    )
    canonical_builder = AsyncMock(return_value=delivery)

    with (
        patch(
            "app.services.runtime_context.build_canonical_context_delivery",
            canonical_builder,
        ),
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_mandates=False,
            include_guardrails=False,
            include_persona_context=False,
        )

    source_ids = [section.source_id for section in sections]
    assert "platform-context" in source_ids
    assert "note-titler" in source_ids
    call = canonical_builder.await_args
    assert call is not None
    request = call.args[1]
    assert request.include_memories is False
    assert request.include_mandates is False
    assert request.include_guardrails is False


def test_dedupe_runtime_prompt_sections_drops_exact_duplicate_content() -> None:
    original = RuntimePromptSection(
        label="Platform Context",
        source_kind="global_prompt",
        source_id="platform-context",
        content="same block",
    )
    duplicate = RuntimePromptSection(
        label="Persona Context",
        source_kind="persona_context",
        source_id="persona",
        content="same block",
    )

    kept, removed = dedupe_runtime_prompt_sections([original, duplicate])

    assert kept == [original]
    assert len(removed) == 1
    assert removed[0].duplicate_of == "global_prompt:platform-context"
    assert removed[0].source_kind == "persona_context"


def test_dedupe_runtime_prompt_sections_drops_whitespace_only_duplicates() -> None:
    original = RuntimePromptSection(
        label="Platform Context",
        source_kind="global_prompt",
        source_id="platform-context",
        content="same   block\n\nwith space",
    )
    duplicate = RuntimePromptSection(
        label="Task Prompt",
        source_kind="task_prompt",
        source_id="heartbeat",
        content=" same block with space ",
    )

    kept, removed = dedupe_runtime_prompt_sections([original, duplicate])

    assert kept == [original]
    assert len(removed) == 1
    assert removed[0].duplicate_of == "global_prompt:platform-context"
