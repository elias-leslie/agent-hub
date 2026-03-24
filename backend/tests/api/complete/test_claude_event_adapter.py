from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.adapters.base import ProviderError
from app.api.complete.claude_event_adapter import adapt_claude_message, adapt_claude_stream


class ResultMessage:
    def __init__(
        self,
        result: str,
        usage: dict[str, int] | None = None,
        finish_reason: str | None = None,
        stop_reason: str | None = None,
        subtype: str = "success",
    ) -> None:
        self.result = result
        self.usage = usage or {}
        self.finish_reason = finish_reason
        self.stop_reason = stop_reason
        self.subtype = subtype


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


def test_adapt_claude_message_uses_stop_reason_when_finish_reason_missing() -> None:
    events = adapt_claude_message(ResultMessage("", stop_reason="max_turns"))
    assert len(events) == 1
    assert events[0].type == "result"
    assert events[0].subtype == "success"
    assert events[0].finish_reason == "max_turns"
    assert events[0].result == ""


def test_adapt_claude_message_maps_error_max_turns_subtype() -> None:
    events = adapt_claude_message(ResultMessage("", subtype="error_max_turns"))
    assert len(events) == 1
    assert events[0].type == "result"
    assert events[0].subtype == "error_max_turns"
    assert events[0].finish_reason == "max_turns"
    assert events[0].result == ""


@pytest.mark.asyncio
async def test_adapt_claude_stream_converts_provider_error_to_error_event() -> None:
    async def _stream():
        yield ResultMessage("partial"), "sdk-session-2"
        raise ProviderError("upstream transient failure", provider="claude")

    events = []
    async for event, session_id in adapt_claude_stream(_stream()):
        events.append((event, session_id))

    assert len(events) == 2
    assert events[0][0].type == "result"
    assert events[1][0].type == "error"
    assert "upstream transient failure" in (events[1][0].error or "")
    assert events[1][1] == "sdk-session-2"


@pytest.mark.asyncio
async def test_adapt_claude_stream_batches_consecutive_top_level_tool_use_blocks() -> None:
    async def _stream():
        yield SimpleNamespace(type="tool_use", id="tool-1", name="Bash", input={"command": "pwd"}), "sdk-session-3"
        yield SimpleNamespace(type="tool_use", id="tool-2", name="Bash", input={"command": "git status"}), "sdk-session-3"
        yield ResultMessage("", finish_reason="max_turns"), "sdk-session-3"

    events = []
    async for event, session_id in adapt_claude_stream(_stream()):
        events.append((event, session_id))

    assert len(events) == 2
    assistant_event, assistant_session_id = events[0]
    assert assistant_session_id == "sdk-session-3"
    assert assistant_event.type == "assistant"
    assert assistant_event.message is not None
    assert [block.id for block in assistant_event.message.content] == ["tool-1", "tool-2"]
    assert [block.name for block in assistant_event.message.content] == ["Bash", "Bash"]
    result_event, result_session_id = events[1]
    assert result_session_id == "sdk-session-3"
    assert result_event.type == "result"
    assert result_event.finish_reason == "max_turns"
