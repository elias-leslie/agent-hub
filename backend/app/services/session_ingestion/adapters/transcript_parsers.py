"""Shared transcript-to-normalized-event parsers for external providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.services.session_ingestion.models import NormalizedEvent

from ._event_builders import _ParseState, append_normalized_events

JsonObject = dict[str, object]


def read_jsonl_lines(transcript_path: str, checkpoint: str | None = None) -> tuple[list[str], str | None]:
    """Read JSONL transcript lines from an optional line-offset checkpoint."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        return [], checkpoint

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return [], checkpoint

    start = int(checkpoint) if checkpoint and checkpoint.isdigit() else 0
    return lines[start:], str(len(lines))


def parse_transcript_events(lines: list[str]) -> list[NormalizedEvent]:
    """Parse supported transcript JSONL entries into normalized events."""
    state = _ParseState()
    for raw_line in lines:
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            append_normalized_events(obj, state)
    return state.events


def read_incremental_transcript_events(
    transcript_path: str,
    checkpoint: str | None = None,
) -> tuple[list[NormalizedEvent], str | None]:
    """Read and parse transcript deltas while preserving parser state across checkpoints."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        return [], checkpoint

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return [], checkpoint

    parser_checkpoint = _load_parse_checkpoint(checkpoint, line_count=len(lines))
    state = _ParseState(
        turn=parser_checkpoint.turn,
        sequence=parser_checkpoint.sequence,
        saw_content=parser_checkpoint.saw_content,
    )
    for raw_line in lines[parser_checkpoint.line_offset :]:
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            append_normalized_events(obj, state)
    return state.events, _dump_parse_checkpoint(line_count=len(lines), state=state)


@dataclass(slots=True)
class _TranscriptParseCheckpoint:
    """Opaque checkpoint for incremental transcript parsing."""

    line_offset: int = 0
    turn: int = 1
    sequence: int = 0
    saw_content: bool = False


def _load_parse_checkpoint(
    checkpoint: str | None,
    *,
    line_count: int,
) -> _TranscriptParseCheckpoint:
    """Load an opaque parser checkpoint, reparsing from start for legacy or invalid values."""
    if not checkpoint or checkpoint.isdigit():
        return _TranscriptParseCheckpoint()
    try:
        parsed = json.loads(checkpoint)
    except json.JSONDecodeError:
        return _TranscriptParseCheckpoint()
    if not isinstance(parsed, dict):
        return _TranscriptParseCheckpoint()
    line_offset = parsed.get("line_offset")
    turn = parsed.get("turn")
    sequence = parsed.get("sequence")
    saw_content = parsed.get("saw_content")
    if not isinstance(line_offset, int) or line_offset < 0 or line_offset > line_count:
        return _TranscriptParseCheckpoint()
    if not isinstance(turn, int) or turn < 1:
        return _TranscriptParseCheckpoint()
    if not isinstance(sequence, int) or sequence < 0:
        return _TranscriptParseCheckpoint()
    if not isinstance(saw_content, bool):
        return _TranscriptParseCheckpoint()
    return _TranscriptParseCheckpoint(
        line_offset=line_offset,
        turn=turn,
        sequence=sequence,
        saw_content=saw_content,
    )


def _dump_parse_checkpoint(*, line_count: int, state: _ParseState) -> str:
    """Serialize the parser state into the opaque checkpoint string."""
    return json.dumps(
        {
            "line_offset": line_count,
            "turn": state.turn,
            "sequence": state.sequence,
            "saw_content": state._saw_content,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
