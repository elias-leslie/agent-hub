from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.api.helpers.agent_preview import build_agent_preview
from app.services.agent_dto import AgentDTO
from app.services.runtime_prompt_stack import RuntimePromptSection


def _agent(*, slug: str = "refactor", memory_config: dict | None = None) -> AgentDTO:
    return AgentDTO(
        id=1,
        slug=slug,
        name=slug.title(),
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-sonnet-4-6",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        memory_config=memory_config,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

def _context(*, mandates=None, guardrails=None):
    mandates = mandates or []
    guardrails = guardrails or []
    return type(
        "Ctx",
        (),
        {
            "mandates": mandates,
            "guardrails": guardrails,
            "reference": [],
            "reference_index": [],
            "debug_info": {},
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
            "get_reference_index_uuids": lambda self: [],
        },
    )()

def _join_preview_sections(sections):
    return "\n\n".join(getattr(section, "content", "") for section in sections if getattr(section, "content", ""))


@pytest.mark.asyncio
async def test_build_agent_preview_uses_runtime_mandate_composition() -> None:
    agent = AgentDTO(
        id=1,
        slug="refactor",
        name="Refactor",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-sonnet-4-6",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [type("M", (), {"uuid": "12345678-aaaa"})()],
            "guardrails": [type("G", (), {"uuid": "87654321-bbbb"})()],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Platform Context",
                    source_kind="global_prompt",
                    source_id="platform-context",
                    content="<platform_context>db prompt</platform_context>",
                )
            ],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="## Mandates\n- [M:12345678] keep prompts in db",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
        )

    assert "<platform_context>db prompt</platform_context>" in preview["combined_prompt"]
    assert "## Mandates" in preview["combined_prompt"]
    assert preview["mandate_count"] == 1
    assert preview["guardrail_count"] == 1
    assert preview["mandate_uuids"] == ["12345678"]
    assert preview["guardrail_uuids"] == ["87654321"]
    assert preview["memory_query"] == ""
    assert preview["loaded_memory_uuids"] == []
    assert preview["reference_uuids"] == []
    assert preview["sections"][0]["source_id"] == "platform-context"
    assert preview["sections"][-1]["source_kind"] == "memory_context"
    assert preview["full_context"].endswith("## Mandates\n- [M:12345678] keep prompts in db")


@pytest.mark.asyncio
async def test_build_agent_preview_adds_task_prompt_as_user_section() -> None:
    agent = AgentDTO(
        id=1,
        slug="persona",
        name="Persona",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-sonnet-4-6",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value="Run your heartbeat now.",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="heartbeat",
        )

    assert preview["task_prompt"] == "Run your heartbeat now."
    assert preview["memory_query"] == "Run your heartbeat now."
    assert preview["sections"][-1]["source_kind"] == "task_prompt"
    assert preview["sections"][-1]["placement"] == "user"
    assert preview["full_context"].endswith("Run your heartbeat now.")
    assert all(section["source_kind"] != "prompt_budget" for section in preview["sections"])


@pytest.mark.asyncio
async def test_build_agent_preview_includes_compact_project_index_when_enabled() -> None:
    agent = AgentDTO(
        id=1,
        slug="coder",
        name="Coder",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="<project-index>\nproject: agent-hub\nurls:\n  api: http://localhost:8003/api\n</project-index>",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            project_id="agent-hub",
            task_type="backend",
        )

    assert preview["sections"][0]["source_kind"] == "project_index"
    assert "<project-index>" in preview["combined_prompt"]
    assert preview["full_context"].startswith("<project-index>")


@pytest.mark.asyncio
async def test_build_agent_preview_includes_tool_capabilities_when_enabled() -> None:
    agent = AgentDTO(
        id=1,
        slug="coder",
        name="Coder",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="<tool-capabilities>\ntools:\n  - tool: st\n</tool-capabilities>",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            project_id="agent-hub",
            task_type="backend",
        )

    assert preview["sections"][0]["source_kind"] == "tool_capabilities"
    assert "<tool-capabilities>" in preview["combined_prompt"]
    assert preview["full_context"].startswith("<tool-capabilities>")


@pytest.mark.asyncio
async def test_build_agent_preview_passes_bash_availability_to_tool_capabilities() -> None:
    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.get_visible_tools_for_project",
            new=AsyncMock(return_value=frozenset({"read_file"})),
            create=True,
        ) as mock_visible_tools,
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ) as mock_tool_capabilities,
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=_context(),
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            _agent(slug="persona"),
            project_id="monkey-fight",
            task_type="wake",
        )

    assert "<tool-capabilities>" not in preview["combined_prompt"]
    assert mock_visible_tools.await_count == 1
    assert mock_tool_capabilities.call_args is not None
    assert mock_tool_capabilities.call_args.kwargs["bash_available"] is False


@pytest.mark.asyncio
async def test_build_agent_preview_passes_agent_memory_config_to_context_builder() -> None:
    agent = AgentDTO(
        id=1,
        slug="memory-curator",
        name="Memory Curator",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        memory_config={"include_references": True, "audience_tags": ["memory-curator"]},
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ) as build_progressive_context,
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Audit one memory target.",
        )

    progressive_args = build_progressive_context.await_args
    assert progressive_args is not None
    assert progressive_args.kwargs["include_mandates"] is True
    assert progressive_args.kwargs["include_guardrails"] is True
    assert progressive_args.kwargs["include_references"] is True
    assert progressive_args.kwargs["memory_config"] == agent.memory_config
    assert progressive_args.kwargs["consumer_profile"] == "agent_preview"


@pytest.mark.asyncio
async def test_build_agent_preview_uses_configured_preview_consumer_profile() -> None:
    agent = AgentDTO(
        id=1,
        slug="coder",
        name="Coder",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        memory_config={"runtime_consumer_profile": "agent_coding"},
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ) as build_progressive_context,
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ) as format_project_index_context,
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ) as format_tool_capability_context,
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Fix one failing test.",
        )

    assert build_progressive_context.await_args is not None
    assert build_progressive_context.await_args.kwargs["consumer_profile"] == "agent_coding"
    assert format_project_index_context.call_args.kwargs["consumer_profile"] == "agent_coding"
    assert format_tool_capability_context.call_args.kwargs["consumer_profile"] == "agent_coding"


@pytest.mark.asyncio
async def test_build_agent_preview_keeps_runtime_prompt_when_injection_disabled() -> None:
    agent = AgentDTO(
        id=1,
        slug="note-titler",
        name="Note Titler",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.1,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config={"enabled": False, "injection_enabled": True},
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Note Titler System Prompt",
                    source_kind="agent_system_prompt",
                    source_id="note-titler",
                    content="<agent_persona>legacy system prompt</agent_persona>",
                )
            ],
        ) as collect_runtime_prompt_sections,
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
        ) as build_progressive_context,
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Title this note.",
        )

    collect_runtime_prompt_sections.assert_awaited_once()
    build_progressive_context.assert_not_awaited()
    assert preview["mandate_count"] == 0
    assert preview["guardrail_count"] == 0
    assert preview["full_context"] == "<agent_persona>legacy system prompt</agent_persona>"
    assert preview["sections"][0]["source_kind"] == "agent_system_prompt"
    collect_args = collect_runtime_prompt_sections.await_args
    assert collect_args is not None
    assert collect_args.kwargs["include_mandates"] is False
    assert collect_args.kwargs["include_guardrails"] is False


@pytest.mark.asyncio
async def test_build_agent_preview_disables_mandate_runtime_prompts_when_include_mandates_disabled() -> None:
    agent = AgentDTO(
        id=1,
        slug="note-titler",
        name="Note Titler",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.1,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config={"include_mandates": False, "include_guardrails": True},
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ) as collect_runtime_prompt_sections,
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Title this note.",
        )

    collect_args = collect_runtime_prompt_sections.await_args
    assert collect_args is not None
    assert collect_args.kwargs["include_mandates"] is False
    assert collect_args.kwargs["include_guardrails"] is True


@pytest.mark.asyncio
async def test_build_agent_preview_respects_memory_config_include_flags() -> None:
    agent = AgentDTO(
        id=1,
        slug="memory-rater",
        name="Memory Rater",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-haiku-4-5",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.1,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config={
            "include_mandates": False,
            "include_guardrails": False,
            "include_references": True,
        },
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ) as build_progressive_context,
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Rate one injected memory.",
        )

    progressive_args = build_progressive_context.await_args
    assert progressive_args is not None
    assert progressive_args.kwargs["include_mandates"] is False
    assert progressive_args.kwargs["include_guardrails"] is False
    assert progressive_args.kwargs["include_references"] is True


@pytest.mark.asyncio
async def test_build_agent_preview_truncates_memory_query_like_runtime_injection() -> None:
    agent = AgentDTO(
        id=1,
        slug="persona",
        name="Persona",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-sonnet-4-6",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()
    long_prompt = "x" * 900

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=long_prompt,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ) as build_progressive_context,
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="heartbeat",
        )

    progressive_args = build_progressive_context.await_args
    assert progressive_args is not None
    assert progressive_args.kwargs["query"] == ("x" * 500)


@pytest.mark.asyncio
async def test_build_agent_preview_uses_task_block_for_wake_memory_query() -> None:
    agent = AgentDTO(
        id=1,
        slug="coder",
        name="Coder",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=(
                "Operational notes:\n"
                "- Use known-good commands.\n"
                "- Open direct-fit references first.\n"
                "Task:\n"
                "Inspect the agent preview command before coding."
            ),
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ) as build_progressive_context,
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="wake",
        )

    progressive_args = build_progressive_context.await_args
    assert progressive_args is not None
    assert (
        progressive_args.kwargs["query"]
        == "Inspect the agent preview command before coding."
    )


@pytest.mark.asyncio
async def test_build_agent_preview_includes_memory_debug() -> None:
    agent = AgentDTO(
        id=1,
        slug="coder",
        name="Coder",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
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

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [],
            "guardrails": [],
            "debug_info": {
                "tier_counts": {"L1": 3, "L2": 2},
                "render_chars_saved": 640,
            },
            "get_loaded_uuids": lambda self: [],
            "get_reference_uuids": lambda self: [],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            side_effect=_join_preview_sections,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            prompt_input="Implement tier-aware memory injection.",
        )

    assert preview["memory_debug"]["tier_counts"] == {"L1": 3, "L2": 2}
    assert preview["memory_debug"]["render_chars_saved"] == 640


async def test_build_agent_preview_adds_budget_warning_for_oversized_prompt() -> None:
    agent = _agent(slug="persona")
    fake_context = _context()
    large_task_prompt = "Run heartbeat.\n" + ("fact\n" * 2500)

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Persona Context",
                    source_kind="persona_context",
                    source_id="persona",
                    content="persona\n" * 1200,
                )
            ],
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=large_task_prompt,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="memory\n" * 1200,
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="heartbeat",
        )

    assert preview["prompt_budget"]["warning_count"] >= 1
    assert preview["prompt_budget"]["severity"] in {"warning", "danger"}
    assert preview["prompt_budget"]["warnings"][0].startswith("Prompt budget")
    assert preview["prompt_budget"]["top_low_yield_sections"]
    assert preview["prompt_budget"]["top_sections"][0]["share_of_total"] > 0
    assert preview["prompt_budget"]["section_breakdown"][0]["share_of_total"] > 0
    assert all(section["source_kind"] != "prompt_budget" for section in preview["sections"])
    assert preview["full_context_estimated_tokens"] >= preview["prompt_budget"]["total_estimated_tokens"]


async def test_build_agent_preview_reports_dropped_duplicate_sections() -> None:
    agent = _agent(slug="persona")
    fake_context = _context()
    same_block = "same block"

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Platform Context",
                    source_kind="global_prompt",
                    source_id="platform-context",
                    content=same_block,
                )
            ],
        ),
        patch(
            "app.api.helpers.agent_preview.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview.format_tool_capability_context",
            return_value="",
        ),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=same_block,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="heartbeat",
        )

    assert preview["prompt_budget"]["dropped_duplicates"]
    assert preview["prompt_budget"]["dropped_duplicates"][0]["duplicate_of"] == "global_prompt:platform-context"
    source_kinds = [section["source_kind"] for section in preview["sections"]]
    assert source_kinds.count("task_prompt") == 1


@pytest.mark.asyncio
async def test_build_agent_preview_recomputes_combined_prompt_after_system_dedupe() -> None:
    agent = _agent(slug="persona")
    fake_context = _context()
    same_block = "same block"

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Platform Context",
                    source_kind="global_prompt",
                    source_id="platform-context",
                    content=same_block,
                )
            ],
        ),
        patch("app.api.helpers.agent_preview.format_project_index_context", return_value=""),
        patch("app.api.helpers.agent_preview.format_tool_capability_context", return_value=""),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value=same_block,
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
            task_type="heartbeat",
        )

    assert preview["prompt_budget"]["dropped_duplicates"]
    assert preview["combined_prompt"].count(same_block) == 1
    assert preview["full_context"].count(same_block) == 1


@pytest.mark.asyncio
async def test_build_agent_preview_dedupes_whitespace_variant_task_prompt() -> None:
    agent = _agent(slug="persona")
    fake_context = _context()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                RuntimePromptSection(
                    label="Platform Context",
                    source_kind="global_prompt",
                    source_id="platform-context",
                    content="same block",
                )
            ],
        ),
        patch("app.api.helpers.agent_preview.format_project_index_context", return_value=""),
        patch("app.api.helpers.agent_preview.format_tool_capability_context", return_value=""),
        patch(
            "app.api.helpers.agent_preview._build_task_prompt_preview",
            new_callable=AsyncMock,
            return_value=" same   block ",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch("app.api.helpers.agent_preview.format_progressive_context", return_value=""),
    ):
        preview = await build_agent_preview(AsyncMock(), agent, task_type="heartbeat")

    assert preview["prompt_budget"]["dropped_duplicates"]
    assert preview["prompt_budget"]["dropped_duplicates"][0]["source_kind"] == "task_prompt"
    assert any(section["source_kind"] == "task_prompt" for section in preview["sections"])
