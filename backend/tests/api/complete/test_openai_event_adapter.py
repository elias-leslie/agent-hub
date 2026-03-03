"""Tests for OpenAI-compat event adapter — StreamEvent → ToolEvent conversion."""

from __future__ import annotations

import time

from app.adapters.types import StreamEvent
from app.api.complete.openai_event_adapter import _tool_start_times, adapt_stream_event


class TestAdaptStreamEvent:
    """Tests for adapt_stream_event conversion."""

    def test_tool_use_event(self) -> None:
        event = StreamEvent(
            type="tool_use", tool_id="tc_1", tool_name="bash", tool_input={"cmd": "ls"},
        )
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "assistant"
        assert result.message is not None
        assert len(result.message.content) == 1
        block = result.message.content[0]
        assert block.type == "tool_use"
        assert block.name == "bash"
        assert block.input == {"cmd": "ls"}
        assert block.id == "tc_1"

    def test_tool_use_records_start_time(self) -> None:
        _tool_start_times.clear()
        event = StreamEvent(
            type="tool_use", tool_id="tc_timer", tool_name="read", tool_input={},
        )
        adapt_stream_event(event)
        assert "tc_timer" in _tool_start_times

    def test_tool_result_event(self) -> None:
        _tool_start_times.clear()
        _tool_start_times["tc_2"] = time.monotonic() - 0.1  # 100ms ago
        event = StreamEvent(type="tool_result", tool_id="tc_2", content="file contents")
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "tool_result"
        assert result.content == "file contents"
        assert result.tool_use_id == "tc_2"
        assert result.is_error is False
        assert result.duration_ms is not None
        assert result.duration_ms >= 90  # ~100ms with tolerance

    def test_tool_result_without_start_time(self) -> None:
        _tool_start_times.clear()
        event = StreamEvent(type="tool_result", tool_id="tc_orphan", content="result")
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "tool_result"
        assert result.duration_ms is None

    def test_tool_result_pops_start_time(self) -> None:
        _tool_start_times.clear()
        _tool_start_times["tc_pop"] = time.monotonic()
        event = StreamEvent(type="tool_result", tool_id="tc_pop", content="ok")
        adapt_stream_event(event)
        assert "tc_pop" not in _tool_start_times

    def test_content_event(self) -> None:
        event = StreamEvent(type="content", content="Hello world")
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "assistant"
        assert result.message is not None
        assert result.message.content[0].type == "text"
        assert result.message.content[0].text == "Hello world"

    def test_empty_content_event_returns_none(self) -> None:
        event = StreamEvent(type="content", content="")
        result = adapt_stream_event(event)
        assert result is None

    def test_done_event(self) -> None:
        event = StreamEvent(type="done")
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "result"
        assert result.subtype == "success"

    def test_error_event(self) -> None:
        event = StreamEvent(type="error", error="connection timeout")
        result = adapt_stream_event(event)
        assert result is not None
        assert result.type == "error"
        assert result.error == "connection timeout"

    def test_unknown_event_returns_none(self) -> None:
        event = StreamEvent(type="turn_start")  # type: ignore[arg-type]
        result = adapt_stream_event(event)
        assert result is None
