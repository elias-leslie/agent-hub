"""Tests for the Codex OAuth adapter tool loop."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.adapters.base import CompletionResult, Message, ToolCallResult
from app.adapters.codex_auth import CodexCredentials
from app.adapters.codex_oauth import CodexOAuthAdapter


@pytest.mark.asyncio
async def test_complete_with_tools_emits_tool_events_and_done() -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    adapter._complete_from_input = AsyncMock(
        side_effect=[
            CompletionResult(
                content="Checking repo",
                model="gpt-5.4",
                provider="codex",
                input_tokens=12,
                output_tokens=4,
                finish_reason="tool_use",
                tool_calls=[ToolCallResult(id="call_1", name="read_file", input={"path": "README.md"})],
                thinking_content="Need the file first.",
            ),
            CompletionResult(
                content="Done",
                model="gpt-5.4",
                provider="codex",
                input_tokens=20,
                output_tokens=6,
                finish_reason="stop",
            ),
        ]
    )

    tool_handler = AsyncMock(return_value="readme contents")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="Read the README")],
        model="codex/gpt-5.4",
        tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=3,
    ):
        events.append(event)

    event_types = [event.type for event in events]
    assert event_types == ["thinking", "content", "tool_use", "tool_result", "content", "done"]
    assert events[2].tool_name == "read_file"
    assert events[2].tool_input == {"path": "README.md"}
    assert events[3].content == "readme contents"
    tool_handler.assert_awaited_once_with("read_file", {"path": "README.md"})


@pytest.mark.asyncio
async def test_complete_with_tools_max_turns_exhaustion() -> None:
    """complete_with_tools emits done/max_turns when tool_use never resolves."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    # Always returns tool_use so the loop never terminates naturally.
    adapter._complete_from_input = AsyncMock(
        return_value=CompletionResult(
            content="",
            model="gpt-5.4",
            provider="codex",
            input_tokens=5,
            output_tokens=2,
            finish_reason="tool_use",
            tool_calls=[ToolCallResult(id="call_x", name="noop", input={})],
        )
    )

    tool_handler = AsyncMock(return_value="ok")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="loop forever")],
        model="codex/gpt-5.4",
        tools=[{"name": "noop", "description": "noop", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=2,
    ):
        events.append(event)

    done_event = events[-1]
    assert done_event.type == "done"
    assert done_event.finish_reason == "max_turns"


@pytest.mark.asyncio
async def test_complete_with_tools_empty_tool_calls_ends_immediately() -> None:
    """complete_with_tools ends immediately when finish_reason is done and tool_calls is empty."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    adapter._complete_from_input = AsyncMock(
        return_value=CompletionResult(
            content="All done",
            model="gpt-5.4",
            provider="codex",
            input_tokens=8,
            output_tokens=3,
            finish_reason="done",
            tool_calls=[],
        )
    )

    tool_handler = AsyncMock()

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="hi")],
        model="codex/gpt-5.4",
        tools=[],
        tool_handler=tool_handler,
        max_turns=5,
    ):
        events.append(event)

    assert events[-1].type == "done"
    assert events[-1].finish_reason == "done"
    tool_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_with_tools_multiple_tool_calls_per_turn() -> None:
    """tool_handler is awaited once for each tool call in a single turn."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    adapter._complete_from_input = AsyncMock(
        side_effect=[
            CompletionResult(
                content="",
                model="gpt-5.4",
                provider="codex",
                input_tokens=10,
                output_tokens=5,
                finish_reason="tool_use",
                tool_calls=[
                    ToolCallResult(id="call_a", name="tool_a", input={"x": 1}),
                    ToolCallResult(id="call_b", name="tool_b", input={"y": 2}),
                    ToolCallResult(id="call_c", name="tool_c", input={"z": 3}),
                ],
            ),
            CompletionResult(
                content="Done",
                model="gpt-5.4",
                provider="codex",
                input_tokens=15,
                output_tokens=4,
                finish_reason="stop",
            ),
        ]
    )

    tool_handler = AsyncMock(return_value="result")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="run tools")],
        model="codex/gpt-5.4",
        tools=[
            {"name": "tool_a", "description": "a", "input_schema": {"type": "object"}},
            {"name": "tool_b", "description": "b", "input_schema": {"type": "object"}},
            {"name": "tool_c", "description": "c", "input_schema": {"type": "object"}},
        ],
        tool_handler=tool_handler,
        max_turns=5,
    ):
        events.append(event)

    tool_use_events = [e for e in events if e.type == "tool_use"]
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_use_events) == 3
    assert len(tool_result_events) == 3
    assert tool_handler.await_count == 3
    tool_handler.assert_any_await("tool_a", {"x": 1})
    tool_handler.assert_any_await("tool_b", {"y": 2})
    tool_handler.assert_any_await("tool_c", {"z": 3})
