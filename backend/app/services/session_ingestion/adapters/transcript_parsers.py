"""Shared transcript-to-normalized-event parsers for external providers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from io import BufferedReader
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
    for index, raw_line in enumerate(lines):
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            state.set_source(obj, f"line:{index}")
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

    parser_checkpoint = _load_parse_checkpoint(checkpoint)
    state = _ParseState(
        turn=parser_checkpoint.turn,
        sequence=parser_checkpoint.sequence,
        saw_content=parser_checkpoint.saw_content,
        history_start_ordinal=parser_checkpoint.history_start_ordinal,
        parent_thread_id=parser_checkpoint.parent_thread_id,
    )
    try:
        with path.open("rb") as transcript:
            stat = os.fstat(transcript.fileno())
            offset = parser_checkpoint.byte_offset
            if parser_checkpoint.legacy:
                legacy_offset = _offset_after_lines(transcript, parser_checkpoint.line_offset)
                if legacy_offset is None:
                    offset = 0
                    state = _ParseState()
                else:
                    offset = legacy_offset
            elif (
                parser_checkpoint.device != stat.st_dev
                or parser_checkpoint.inode != stat.st_ino
                or offset > stat.st_size
                or _tail_digest(transcript, offset) != parser_checkpoint.tail_digest
            ):
                offset = 0
            transcript.seek(offset)
            line_count = parser_checkpoint.line_offset if offset else 0
            while raw_line := transcript.readline():
                if not raw_line.endswith(b"\n"):
                    break  # The writer has not completed this JSONL entry yet.
                line_start = offset
                offset = transcript.tell()
                line_count += 1
                try:
                    obj = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(obj, dict):
                    ordinal = obj.get("ordinal")
                    # A transcript can be truncated and rewritten on the same inode.
                    # Include the line content so reused ordinals and offsets do not
                    # collapse replacement events into the previous generation.
                    line_digest = hashlib.sha256(raw_line).hexdigest()[:16]
                    identity = (
                        f"{stat.st_dev}:{stat.st_ino}:ordinal:{ordinal}:{line_digest}"
                        if isinstance(ordinal, int) and not isinstance(ordinal, bool)
                        else f"{stat.st_dev}:{stat.st_ino}:byte:{line_start}:{line_digest}"
                    )
                    state.set_source(obj, identity)
                    append_normalized_events(obj, state)
            tail_digest = _tail_digest(transcript, offset)
    except OSError:
        return [], checkpoint
    return state.events, _dump_parse_checkpoint(
        line_count=line_count,
        byte_offset=offset,
        device=stat.st_dev,
        inode=stat.st_ino,
        tail_digest=tail_digest,
        state=state,
    )


@dataclass(slots=True)
class _TranscriptParseCheckpoint:
    """Opaque checkpoint for incremental transcript parsing."""

    line_offset: int = 0
    byte_offset: int = 0
    device: int | None = None
    inode: int | None = None
    tail_digest: str | None = None
    legacy: bool = False
    turn: int = 1
    sequence: int = 0
    saw_content: bool = False
    history_start_ordinal: int | None = None
    parent_thread_id: str | None = None


def _load_parse_checkpoint(
    checkpoint: str | None,
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
    history_start_ordinal = parsed.get("history_start_ordinal")
    parent_thread_id = parsed.get("parent_thread_id")
    byte_offset = parsed.get("byte_offset")
    device = parsed.get("device")
    inode = parsed.get("inode")
    tail_digest = parsed.get("tail_digest")
    if not isinstance(line_offset, int) or line_offset < 0:
        return _TranscriptParseCheckpoint()
    if not isinstance(turn, int) or turn < 1:
        return _TranscriptParseCheckpoint()
    if not isinstance(sequence, int) or sequence < 0:
        return _TranscriptParseCheckpoint()
    if not isinstance(saw_content, bool):
        return _TranscriptParseCheckpoint()
    if history_start_ordinal is not None and (
        not isinstance(history_start_ordinal, int) or history_start_ordinal < 0
    ):
        return _TranscriptParseCheckpoint()
    if parent_thread_id is not None and not isinstance(parent_thread_id, str):
        return _TranscriptParseCheckpoint()
    # Existing JSON checkpoints carry valid parser state but no byte position.
    # Scan their completed prefix once; never reinterpret old rows using new event kinds.
    if byte_offset is None:
        return _TranscriptParseCheckpoint(
            line_offset=line_offset, turn=turn, sequence=sequence,
            saw_content=saw_content, legacy=True,
            history_start_ordinal=history_start_ordinal,
            parent_thread_id=parent_thread_id,
        )
    if not isinstance(byte_offset, int) or byte_offset < 0:
        return _TranscriptParseCheckpoint()
    if not isinstance(device, int) or not isinstance(inode, int) or not isinstance(tail_digest, str):
        return _TranscriptParseCheckpoint()
    return _TranscriptParseCheckpoint(
        line_offset=line_offset,
        byte_offset=byte_offset,
        device=device,
        inode=inode,
        tail_digest=tail_digest,
        turn=turn,
        sequence=sequence,
        saw_content=saw_content,
        history_start_ordinal=history_start_ordinal,
        parent_thread_id=parent_thread_id,
    )


def _offset_after_lines(transcript: BufferedReader, line_count: int) -> int | None:
    """Upgrade an old line checkpoint without changing historical sequences."""
    transcript.seek(0)
    offset = 0
    for _ in range(line_count):
        raw_line = transcript.readline()
        if not raw_line or not raw_line.endswith(b"\n"):
            return None  # The old source was truncated or replaced.
        offset = transcript.tell()
    return offset


def _tail_digest(transcript: BufferedReader, offset: int) -> str:
    """Verify a small committed prefix without rereading the growing transcript."""
    transcript.seek(max(0, offset - 128))
    tail = transcript.read(min(128, offset))
    return hashlib.sha256(tail).hexdigest()


def _dump_parse_checkpoint(
    *,
    line_count: int,
    byte_offset: int,
    device: int,
    inode: int,
    tail_digest: str,
    state: _ParseState,
) -> str:
    """Serialize the parser state into the opaque checkpoint string."""
    return json.dumps(
        {
            "line_offset": line_count,
            "byte_offset": byte_offset,
            "device": device,
            "inode": inode,
            "tail_digest": tail_digest,
            "turn": state.turn,
            "sequence": state.sequence,
            "saw_content": state._saw_content,
            "history_start_ordinal": state.history_start_ordinal,
            "parent_thread_id": state.parent_thread_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
