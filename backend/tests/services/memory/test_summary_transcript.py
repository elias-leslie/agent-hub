"""Tests for session summary transcript building."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.memory.summary_transcript import (
    MAX_TRANSCRIPT_LINES,
    RECENCY_RATIO,
    _apply_recency_window,
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

    def test_long_transcript_uses_recency_window(self) -> None:
        """Long transcripts use recency-biased windowing, not flat truncation."""
        events = [_event("user_message", content=f"msg {i}") for i in range(150)]
        result = build_condensed_transcript(events)
        lines = result.strip().split("\n")

        # Recency window: 30 early + 1 separator + recent lines
        assert len(lines) <= MAX_TRANSCRIPT_LINES + 1  # +1 for separator
        assert "--- [recent work below] ---" in result

        # Early context preserved (first 30 lines of the first 75%)
        assert "USER: msg 0" in lines[0]
        assert "USER: msg 29" in lines[29]

        # Most recent content preserved
        assert "USER: msg 149" in lines[-1]

    def test_user_content_truncated_at_1000_chars(self) -> None:
        """Long user content is truncated to 1000 characters."""
        long_content = "x" * 2000
        events = [_event("user_message", content=long_content)]
        result = build_condensed_transcript(events)
        # "USER: " prefix + 1000 chars
        assert len(result) == len("USER: ") + 1000

    def test_assistant_content_truncated_at_500_chars(self) -> None:
        """Long assistant content is truncated to 500 characters."""
        long_content = "x" * 1000
        events = [_event("assistant_message", content=long_content)]
        result = build_condensed_transcript(events)
        # "ASSISTANT: " prefix + 500 chars
        assert len(result) == len("ASSISTANT: ") + 500

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

    def test_long_jsonl_uses_recency_window(self) -> None:
        """Long JSONL transcripts use recency-biased windowing."""
        from app.services.memory.summary_transcript import (
            build_condensed_transcript_from_jsonl,
        )

        jsonl_lines = [
            f'{{"type": "user", "message": {{"role": "user", "content": "msg {i}"}}}}'
            for i in range(150)
        ]
        result = build_condensed_transcript_from_jsonl(jsonl_lines)
        lines = result.strip().split("\n")
        assert len(lines) <= MAX_TRANSCRIPT_LINES + 1  # +1 for separator
        assert "--- [recent work below] ---" in result
        assert "USER: msg 0" in lines[0]
        assert "USER: msg 149" in lines[-1]

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


@pytest.mark.unit
class TestRecencyWindow:
    """Tests for _apply_recency_window function."""

    def test_short_transcript_keeps_all_lines(self) -> None:
        """Transcripts under MAX_TRANSCRIPT_LINES are returned unchanged."""
        lines = [f"USER: msg {i}" for i in range(50)]
        result = _apply_recency_window(lines)
        assert result == "\n".join(lines)
        assert "--- [recent work below] ---" not in result

    def test_exact_threshold_keeps_all_lines(self) -> None:
        """Transcript at exactly MAX_TRANSCRIPT_LINES is returned unchanged."""
        lines = [f"USER: msg {i}" for i in range(MAX_TRANSCRIPT_LINES)]
        result = _apply_recency_window(lines)
        assert result == "\n".join(lines)
        assert "--- [recent work below] ---" not in result

    def test_over_threshold_applies_windowing(self) -> None:
        """Transcript exceeding MAX_TRANSCRIPT_LINES triggers recency windowing."""
        lines = [f"USER: msg {i}" for i in range(200)]
        result = _apply_recency_window(lines)
        result_lines = result.split("\n")

        assert "--- [recent work below] ---" in result
        assert len(result_lines) <= MAX_TRANSCRIPT_LINES + 1  # +1 for separator

    def test_recent_section_dominates(self) -> None:
        """Recent content gets ~70% of the budget, early ~30%."""
        lines = [f"LINE {i}" for i in range(500)]
        result = _apply_recency_window(lines)
        result_lines = result.split("\n")

        sep_idx = result_lines.index("--- [recent work below] ---")
        early_count = sep_idx
        recent_count = len(result_lines) - sep_idx - 1

        # 30% early, 70% recent
        expected_early = MAX_TRANSCRIPT_LINES - int(MAX_TRANSCRIPT_LINES * RECENCY_RATIO)
        expected_recent = int(MAX_TRANSCRIPT_LINES * RECENCY_RATIO)
        assert early_count == expected_early  # 30
        assert recent_count == expected_recent  # 70

    def test_latest_entries_always_present(self) -> None:
        """The very last lines of the original transcript appear in output."""
        lines = [f"LINE {i}" for i in range(300)]
        result = _apply_recency_window(lines)
        assert "LINE 299" in result
        assert "LINE 298" in result


def _event(
    event_type: str,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock SessionEvent."""
    event = MagicMock()
    event.event_type = event_type
    event.content = content
    event.tool_name = tool_name
    event.tool_input = tool_input
    event.tool_output = tool_output
    return event
