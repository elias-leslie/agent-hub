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
