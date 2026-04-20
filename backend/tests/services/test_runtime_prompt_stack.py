from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_dto import AgentDTO
from app.services.owned_prompt_service import (
    AGENT_SYSTEM_PROMPT_TYPE,
    GLOBAL_GUARDRAIL_PROMPT_TYPE,
    GLOBAL_MANDATE_PROMPT_TYPE,
)
from app.services.runtime_prompt_stack import (
    RuntimePromptSection,
    collect_runtime_prompt_sections,
    dedupe_runtime_prompt_sections,
)


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
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_adds_agent_system_prompt_when_unassigned() -> None:
    agent = _agent()

    with (
        patch(
            "app.services.runtime_prompt_stack.get_all_prompts",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
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
            prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
            name="Note Titler System Prompt",
            slug="note-titler-system-prompt",
            content="<agent_persona>\nCanonical prompt\n</agent_persona>",
            updated_at=None,
        ),
    )

    with (
        patch(
            "app.services.runtime_prompt_stack.get_all_prompts",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[assignment]),
        ),
    ):
        sections = await collect_runtime_prompt_sections(
            AsyncMock(),
            agent,
            include_persona_context=False,
        )

    assert len(sections) == 1
    assert sections[0].source_kind == "agent_system_prompt"
    assert sections[0].source_id == "note-titler-system-prompt"
    assert "Canonical prompt" in sections[0].content


@pytest.mark.asyncio
async def test_collect_runtime_prompt_sections_filters_typed_global_prompts() -> None:
    agent = _agent()
    global_prompts = [
        SimpleNamespace(
            enabled=True,
            prompt_type=GLOBAL_MANDATE_PROMPT_TYPE,
            name="Narration Tags",
            slug="narration-tags",
            content="MANDATE",
            updated_at=None,
            exclude_agents=[],
        ),
        SimpleNamespace(
            enabled=True,
            prompt_type=GLOBAL_GUARDRAIL_PROMPT_TYPE,
            name="Safety Directive",
            slug="safety-directive",
            content="GUARDRAIL",
            updated_at=None,
            exclude_agents=[],
        ),
        SimpleNamespace(
            enabled=True,
            prompt_type="standard",
            name="Platform Context",
            slug="platform-context",
            content="CONTEXT",
            updated_at=None,
            exclude_agents=[],
        ),
    ]

    with (
        patch(
            "app.services.runtime_prompt_stack.get_all_prompts",
            new=AsyncMock(return_value=global_prompts),
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
    assert "narration-tags" not in source_ids
    assert "safety-directive" not in source_ids
    assert "platform-context" in source_ids
    assert "note-titler" in source_ids


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
