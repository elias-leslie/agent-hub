"""Tests for session summary transcript building."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.memory.summary_transcript import (
    build_condensed_transcript,
)


@pytest.mark.unit
class TestBuildCondensedTranscript:
    """Tests for build_condensed_transcript."""

    def test_user_and_assistant_messages(self) -> None:
        """Extracts user and assistant messages from events."""
        events = [
            _event("user_message", content="Hello, world"),
            _event("assistant_message", content="Hi there!"),
        ]
        result = build_condensed_transcript(events)
        assert "USER: Hello, world" in result
        assert "ASSISTANT: Hi there!" in result

    def test_tool_use_with_input(self) -> None:
        """Extracts tool use events with input preview."""
        events = [
            _event("tool_use", tool_name="Read", tool_input={"file": "/foo.py"}),
        ]
        result = build_condensed_transcript(events)
        assert "TOOL: Read" in result
        assert "/foo.py" in result

    def test_tool_result(self) -> None:
        """Extracts tool result events."""
        events = [
            _event("tool_result", tool_output={"output": "file content here"}),
        ]
        result = build_condensed_transcript(events)
        assert "RESULT:" in result
        assert "file content here" in result

    def test_error_events(self) -> None:
        """Extracts error events."""
        events = [
            _event("error", content="Something went wrong"),
        ]
        result = build_condensed_transcript(events)
        assert "ERROR: Something went wrong" in result

    def test_null_content_skipped(self) -> None:
        """Events with null content are skipped silently."""
        events = [
            _event("user_message", content=None),
            _event("assistant_message", content=None),
            _event("user_message", content="actual message"),
        ]
        result = build_condensed_transcript(events)
        assert result == "USER: actual message"

    def test_empty_string_content_skipped(self) -> None:
        """Events with empty string content are skipped."""
        events = [
            _event("assistant_message", content=""),
            _event("user_message", content="real content"),
        ]
        result = build_condensed_transcript(events)
        assert result == "USER: real content"

    def test_unknown_event_types_skipped(self) -> None:
        """Events with unrecognized types are skipped."""
        events = [
            _event("memory_cite", content="Cited 4 rules"),
            _event("memory_inject", content="Injected context"),
            _event("user_message", content="hello"),
        ]
        result = build_condensed_transcript(events)
        assert "memory" not in result.lower()
        assert "USER: hello" in result

    def test_max_100_lines(self) -> None:
        """Output limited to last 100 lines."""
        events = [_event("user_message", content=f"msg {i}") for i in range(150)]
        result = build_condensed_transcript(events)
        lines = result.strip().split("\n")
        assert len(lines) == 100
        # Should have the LAST 100 messages (50-149)
        assert "USER: msg 50" in lines[0]
        assert "USER: msg 149" in lines[-1]

    def test_content_truncated_at_500_chars(self) -> None:
        """Long content is truncated to 500 characters."""
        long_content = "x" * 1000
        events = [_event("user_message", content=long_content)]
        result = build_condensed_transcript(events)
        # "USER: " prefix + 500 chars
        assert len(result) == len("USER: ") + 500

    def test_empty_events_returns_empty_string(self) -> None:
        """Empty event list returns empty string."""
        result = build_condensed_transcript([])
        assert result == ""

    def test_all_null_content_returns_empty_string(self) -> None:
        """Events where all content is null returns empty string."""
        events = [
            _event("user_message", content=None),
            _event("assistant_message", content=None),
            _event("tool_use", tool_name=None),
        ]
        result = build_condensed_transcript(events)
        assert result == ""


@pytest.mark.unit
class TestBuildCondensedTranscriptFromJsonl:
    """Tests for build_condensed_transcript_from_jsonl."""

    def test_extracts_user_and_assistant_from_jsonl(self) -> None:
        """Extracts user and assistant messages from JSONL lines."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            '{"type": "user", "message": {"role": "user", "content": "Fix the bug"}}',
            '{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "I\'ll fix it now"}]}}',
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        assert "USER: Fix the bug" in result
        assert "ASSISTANT: I'll fix it now" in result

    def test_extracts_tool_use_from_jsonl(self) -> None:
        """Extracts tool_use blocks from assistant messages."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            '{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/foo.py"}}]}}',
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        assert "TOOL: Read" in result

    def test_skips_non_conversation_types(self) -> None:
        """Skips progress, file-history-snapshot, system etc."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            '{"type": "progress", "data": "something"}',
            '{"type": "file-history-snapshot", "snapshot": {}}',
            '{"type": "system", "message": {"content": "system msg"}}',
            '{"type": "user", "message": {"role": "user", "content": "actual"}}',
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        assert "progress" not in result.lower()
        assert "snapshot" not in result.lower()
        assert "USER: actual" in result

    def test_handles_content_as_list_of_text_blocks(self) -> None:
        """Handles content as list with text blocks."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            '{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "multi block"}]}}',
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        assert "USER: multi block" in result

    def test_max_100_lines_from_jsonl(self) -> None:
        """Output limited to last 100 lines."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            f'{{"type": "user", "message": {{"role": "user", "content": "msg {i}"}}}}'
            for i in range(150)
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        lines = result.strip().split("\n")
        assert len(lines) == 100

    def test_empty_lines_returns_empty_string(self) -> None:
        """Empty input returns empty string."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        result = build_condensed_transcript_from_jsonl([])
        assert result == ""

    def test_malformed_json_skipped(self) -> None:
        """Malformed JSON lines are skipped gracefully."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            "not json at all",
            '{"type": "user", "message": {"role": "user", "content": "valid"}}',
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        assert "USER: valid" in result


def _event(
    event_type: str,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    tool_output: dict | None = None,
) -> MagicMock:
    """Create a mock SessionEvent."""
    event = MagicMock()
    event.event_type = event_type
    event.content = content
    event.tool_name = tool_name
    event.tool_input = tool_input
    event.tool_output = tool_output
    return event
