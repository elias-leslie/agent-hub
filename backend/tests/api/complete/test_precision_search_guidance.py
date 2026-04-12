"""Tests for Precision Code Search soft guidance."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete._core_helpers import execute_and_build_result
from app.api.complete.precision_search_guidance import (
    PRECISION_CODE_SEARCH_REMINDER,
    maybe_inject_claude_tool_alias_guidance,
    maybe_inject_precision_search_guidance,
    should_inject_precision_search_guidance,
)
from app.api.complete.tool_provisioner import ToolProvisioningResult
from app.api.complete.types import CompletionInternalResult


def test_should_inject_for_code_navigation_query() -> None:
    messages = [{"role": "user", "content": "Where is get_file_tree implemented?"}]
    tools = [{"name": "precision_code_search"}]

    assert should_inject_precision_search_guidance(messages, tools) is True


def test_should_inject_for_tool_registration_query() -> None:
    messages = [
        {
            "role": "user",
            "content": "Is precision_code_search already wired into the shared tool registry for persona?",
        }
    ]
    tools = [{"name": "precision_code_search"}]

    assert should_inject_precision_search_guidance(messages, tools) is True


def test_should_not_inject_for_workflow_query() -> None:
    messages = [{"role": "user", "content": "What is the cleanup status for this repo?"}]
    tools = [{"name": "precision_code_search"}]

    assert should_inject_precision_search_guidance(messages, tools) is False


def test_should_not_inject_after_precision_search_was_already_used() -> None:
    messages = [
        {"role": "user", "content": "Where is get_file_tree implemented?"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "precision_code_search",
                    "input": {"query": "get_file_tree"},
                }
            ],
        },
    ]
    tools = [{"name": "precision_code_search"}]

    assert should_inject_precision_search_guidance(messages, tools) is False


def test_should_not_inject_after_claude_prefixed_precision_search_was_already_used() -> None:
    messages = [
        {"role": "user", "content": "Where is get_file_tree implemented?"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__agent-hub__precision_code_search",
                    "input": {"query": "get_file_tree"},
                }
            ],
        },
    ]
    tools = [{"name": "precision_code_search"}]

    assert should_inject_precision_search_guidance(messages, tools) is False


def test_maybe_inject_inserts_system_message_after_existing_system_messages() -> None:
    messages = [
        {"role": "system", "content": "Existing rule"},
        {"role": "user", "content": "Find UserContextService usages"},
    ]

    guided, injected = maybe_inject_precision_search_guidance(
        messages,
        [{"name": "precision_code_search"}],
    )

    assert injected is True
    assert guided[0]["content"] == "Existing rule"
    assert guided[1]["role"] == "system"
    assert guided[1]["content"] == PRECISION_CODE_SEARCH_REMINDER


def test_maybe_inject_claude_alias_guidance_uses_mcp_examples() -> None:
    guided, injected = maybe_inject_claude_tool_alias_guidance(
        [{"role": "user", "content": "Use research_web once."}],
        [
            {"name": "bash"},
            {"name": "research_web"},
            {"name": "search_web"},
            {"name": "fetch_web_page"},
        ],
        provider="claude",
    )

    assert injected is True
    assert guided[0]["role"] == "system"
    assert "mcp__agent-hub__<tool_name>" in guided[0]["content"]
    assert "`research_web` -> `mcp__agent-hub__research_web`" in guided[0]["content"]


def test_maybe_inject_claude_alias_guidance_skips_non_claude_provider() -> None:
    guided, injected = maybe_inject_claude_tool_alias_guidance(
        [{"role": "user", "content": "Use research_web once."}],
        [{"name": "research_web"}],
        provider="codex",
    )

    assert injected is False
    assert guided == [{"role": "user", "content": "Use research_web once."}]


def test_reminder_mentions_tool_registration_and_exact_symbol_name() -> None:
    assert "tool definitions" in PRECISION_CODE_SEARCH_REMINDER
    assert "exact symbol" in PRECISION_CODE_SEARCH_REMINDER


@pytest.mark.asyncio
async def test_execute_and_build_result_skips_precision_reminder_before_tool_execution() -> None:
    captured_messages: list[dict[str, object]] = []

    async def _capture_loop(ctx, *, should_execute_tools):
        assert should_execute_tools is True
        captured_messages.extend(ctx.messages_dict)
        return CompletionInternalResult(
            content="done",
            model="codex/gpt-5.4",
            provider="codex",
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
            session_id="sess-1",
            memory_uuids=[],
            cited_uuids=[],
        )

    provisioned = ToolProvisioningResult(
        loaded_tools=[{"name": "precision_code_search", "description": "x", "input_schema": {"type": "object"}}],
        catalog_tools=[{"name": "precision_code_search", "description": "x", "input_schema": {"type": "object"}}],
    )

    with (
        patch(
            "app.api.complete._core_helpers.provision_standard_tools",
            return_value=provisioned,
        ),
        patch(
            "app.api.complete.tool_router.supports_tools",
            return_value=True,
        ),
        patch(
            "app.api.complete._core_helpers.execute_agent_loop",
            new=AsyncMock(side_effect=_capture_loop),
        ),
    ):
        await execute_and_build_result(
            provider="codex",
            model="codex/gpt-5.4",
            temperature=0.0,
            project_id="summitflow",
            messages_dict=[{"role": "user", "content": "Where is get_file_tree implemented?"}],
            user_messages_for_db=[],
            tools=None,
            working_dir=None,
            db=AsyncMock(),
            session=SimpleNamespace(),
            session_id="sess-1",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            skip_cache=True,
            progress_callback=None,
            max_turns=1,
            execute_tools=True,
            enable_programmatic_tools=False,
            defer_tool_loading=False,
            enable_caching=False,
            cache_ttl="ephemeral",
            task_type=None,
            thinking_level=None,
            container_id=None,
            response_format=None,
            agent_slug="coder",
        )

    assert captured_messages == [
        {"role": "user", "content": "Where is get_file_tree implemented?"},
    ]


@pytest.mark.asyncio
async def test_execute_and_build_result_injects_only_claude_alias_guidance() -> None:
    captured_messages: list[dict[str, object]] = []

    async def _capture_loop(ctx, *, should_execute_tools):
        assert should_execute_tools is True
        captured_messages.extend(ctx.messages_dict)
        return CompletionInternalResult(
            content="done",
            model="claude-sonnet-4-6",
            provider="claude",
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
            session_id="sess-1",
            memory_uuids=[],
            cited_uuids=[],
        )

    provisioned = ToolProvisioningResult(
        loaded_tools=[
            {"name": "precision_code_search", "description": "x", "input_schema": {"type": "object"}},
            {"name": "research_web", "description": "x", "input_schema": {"type": "object"}},
        ],
        catalog_tools=[
            {"name": "precision_code_search", "description": "x", "input_schema": {"type": "object"}},
            {"name": "research_web", "description": "x", "input_schema": {"type": "object"}},
        ],
    )

    with (
        patch(
            "app.api.complete._core_helpers.provision_standard_tools",
            return_value=provisioned,
        ),
        patch(
            "app.api.complete.tool_router.supports_tools",
            return_value=True,
        ),
        patch(
            "app.api.complete._core_helpers.execute_agent_loop",
            new=AsyncMock(side_effect=_capture_loop),
        ),
    ):
        await execute_and_build_result(
            provider="claude",
            model="claude-sonnet-4-6",
            temperature=0.0,
            project_id="agent-hub",
            messages_dict=[{"role": "user", "content": "Where is get_file_tree implemented?"}],
            user_messages_for_db=[],
            tools=None,
            working_dir=None,
            db=AsyncMock(),
            session=SimpleNamespace(),
            session_id="sess-1",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            skip_cache=True,
            progress_callback=None,
            max_turns=1,
            execute_tools=True,
            enable_programmatic_tools=False,
            defer_tool_loading=False,
            enable_caching=False,
            cache_ttl="ephemeral",
            task_type=None,
            thinking_level=None,
            container_id=None,
            response_format=None,
            agent_slug="analyst",
        )

    assert captured_messages[0]["role"] == "system"
    assert "mcp__agent-hub__<tool_name>" in str(captured_messages[0]["content"])
    assert captured_messages[1] == {
        "role": "user",
        "content": "Where is get_file_tree implemented?",
    }
