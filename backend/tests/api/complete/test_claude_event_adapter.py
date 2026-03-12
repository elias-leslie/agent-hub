from __future__ import annotations

import pytest

from app.adapters.base import ProviderError
from app.api.complete.claude_event_adapter import adapt_claude_message, adapt_claude_stream


class ResultMessage:
    def __init__(
        self,
        result: str,
        usage: dict[str, int] | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.result = result
        self.usage = usage or {}
        self.finish_reason = finish_reason


@pytest.mark.asyncio
async def test_adapt_claude_stream_emits_terminal_result_event() -> None:
    async def _stream():
        yield ResultMessage("Final summary"), "sdk-session-1"

    events = []
    async for event, session_id in adapt_claude_stream(_stream()):
        events.append((event, session_id))

    assert len(events) == 1
    event, session_id = events[0]
    assert session_id == "sdk-session-1"
    assert event.type == "result"
    assert event.result == "Final summary"


def test_adapt_claude_message_ignores_empty_result_message() -> None:
    events = adapt_claude_message(ResultMessage("   "))
    assert len(events) == 1
    assert events[0].type == "result"
    assert events[0].finish_reason == "end_turn"
    assert events[0].result == ""


def test_adapt_claude_message_preserves_finish_reason_for_empty_result_message() -> None:
    events = adapt_claude_message(ResultMessage("", finish_reason="max_turns"))
    assert len(events) == 1
    assert events[0].type == "result"
    assert events[0].finish_reason == "max_turns"
    assert events[0].result == ""


@pytest.mark.asyncio
async def test_adapt_claude_stream_converts_provider_error_to_error_event() -> None:
    async def _stream():
        yield ResultMessage("partial"), "sdk-session-2"
        raise ProviderError("Claude SDK stalled after tool_result for 300.0s", provider="claude")

    events = []
    async for event, session_id in adapt_claude_stream(_stream()):
        events.append((event, session_id))

    assert len(events) == 2
    assert events[0][0].type == "result"
    assert events[1][0].type == "error"
    assert "stalled after tool_result" in (events[1][0].error or "")
    assert events[1][1] == "sdk-session-2"
