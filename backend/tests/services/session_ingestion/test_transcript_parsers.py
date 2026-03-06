"""Tests for transcript-to-normalized-event parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.session_ingestion.adapters.transcript_parsers import (
    parse_transcript_events,
    read_jsonl_lines,
)


@pytest.mark.unit
class TestParseTranscriptEvents:
    """Tests for parsing Claude and Codex JSONL transcripts."""

    def test_parses_claude_transcript_into_stable_turns(self) -> None:
        lines = [
            '{"type":"user","message":{"role":"user","content":"Inspect hooks"}}',
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Tracing now"},{"type":"tool_use","name":"Read","input":{"file_path":"/tmp/x.py"}}]}}',
            '{"type":"user","message":{"role":"user","content":"Patch it"}}',
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]}}',
        ]

        events = parse_transcript_events(lines)

        assert [(event.event_type, event.turn, event.sequence) for event in events] == [
            ("user_message", 1, 1),
            ("assistant_message", 1, 2),
            ("tool_use", 1, 3),
            ("user_message", 2, 1),
            ("assistant_message", 2, 2),
        ]

    def test_parses_codex_transcript_into_normalized_events(self) -> None:
        lines = [
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Review parser"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Tracing now"}]}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"git status\\"}"}}',
            '{"type":"response_item","payload":{"type":"function_call_output","output":"M backend/app.py"}}',
        ]

        events = parse_transcript_events(lines)

        assert [(event.event_type, event.turn, event.sequence) for event in events] == [
            ("user_message", 1, 1),
            ("assistant_message", 1, 2),
            ("tool_use", 1, 3),
            ("tool_result", 1, 4),
        ]
        assert events[2].tool_name == "exec_command"
        assert events[3].content == "M backend/app.py"


@pytest.mark.unit
def test_read_jsonl_lines_respects_line_offset_checkpoint(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\ntwo\nthree\n")

    lines, checkpoint = read_jsonl_lines(str(transcript), checkpoint="1")

    assert lines == ["two", "three"]
    assert checkpoint == "3"
