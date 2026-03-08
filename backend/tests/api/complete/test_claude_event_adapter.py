from __future__ import annotations

import pytest

from app.api.complete.claude_event_adapter import adapt_claude_message, adapt_claude_stream


class ResultMessage:
    def __init__(self, result: str, usage: dict[str, int] | None = None) -> None:
        self.result = result
        self.usage = usage or {}


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
    assert events == []
