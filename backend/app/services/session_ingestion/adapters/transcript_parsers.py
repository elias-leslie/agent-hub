"""Shared transcript-to-normalized-event parsers for external providers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BufferedReader
from pathlib import Path

from app.services.session_ingestion.models import (
    NormalizedEvent,
    TranscriptSourceHealth,
    TranscriptSourceIssue,
)

from ._event_builders import _ParseState, append_normalized_events

JsonObject = dict[str, object]
PARSER_VERSION = "agent-hub.transcript-jsonl.v2"


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
        active_exec_call_ids=parser_checkpoint.active_exec_call_ids,
    )
    parse_issue_counts = dict(parser_checkpoint.parse_issue_counts)
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
                except json.JSONDecodeError:
                    parse_issue_counts["malformed_json"] = (
                        parse_issue_counts.get("malformed_json", 0) + 1
                    )
                    continue
                except UnicodeDecodeError:
                    parse_issue_counts["invalid_utf8"] = (
                        parse_issue_counts.get("invalid_utf8", 0) + 1
                    )
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
                else:
                    parse_issue_counts["non_object_json"] = (
                        parse_issue_counts.get("non_object_json", 0) + 1
                    )
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
        parse_issue_counts=parse_issue_counts,
    )


def inspect_transcript_source(
    transcript_path: str,
    checkpoint: str | None,
) -> TranscriptSourceHealth:
    """Compare one committed parser cursor with the source currently on disk."""
    observed_at = datetime.now(UTC)
    path = Path(transcript_path)
    if path.suffix != ".jsonl" or not path.exists():
        return TranscriptSourceHealth(
            state="blocked",
            observed_at=observed_at,
            parser_version=PARSER_VERSION,
            issues=[TranscriptSourceIssue(
                code="source_missing",
                detail="The native JSONL transcript is unavailable.",
            )],
        )
    try:
        stat = path.stat()
    except OSError:
        return TranscriptSourceHealth(
            state="blocked",
            observed_at=observed_at,
            parser_version=PARSER_VERSION,
            issues=[TranscriptSourceIssue(
                code="source_unreadable",
                detail="The native JSONL transcript could not be observed.",
            )],
        )

    parsed = _load_parse_checkpoint(checkpoint)
    generation = hashlib.sha256(
        f"{stat.st_dev}:{stat.st_ino}".encode()
    ).hexdigest()
    identity_matches = (
        parsed.device == stat.st_dev
        and parsed.inode == stat.st_ino
        and parsed.byte_offset <= stat.st_size
    )
    issues: list[TranscriptSourceIssue] = []
    if not identity_matches:
        issues.append(TranscriptSourceIssue(
            code="source_generation_unverified",
            detail="The committed parser cursor does not match the observed source generation.",
        ))
    committed = parsed.byte_offset if identity_matches else 0
    pending = stat.st_size - committed
    if identity_matches and pending:
        issues.append(TranscriptSourceIssue(
            code="source_not_caught_up",
            detail="The source contains bytes beyond the committed parser cursor.",
        ))
    for code, count in sorted(parsed.parse_issue_counts.items()):
        issues.append(TranscriptSourceIssue(
            code=code,
            count=count,
            detail="The parser skipped one or more complete native transcript records.",
        ))
    if parsed.active_exec_call_ids:
        issues.append(TranscriptSourceIssue(
            code="unresolved_tool_calls",
            count=len(parsed.active_exec_call_ids),
            detail="One or more native tool starts have no committed result.",
        ))
    caught_up = identity_matches and pending == 0
    return TranscriptSourceHealth(
        state="ready" if caught_up and not issues else "incomplete",
        observed_at=observed_at,
        parser_version=PARSER_VERSION,
        source_generation=generation,
        committed_line_count=parsed.line_offset if identity_matches else 0,
        committed_byte_offset=committed,
        observed_extent=stat.st_size,
        pending_bytes=pending,
        caught_up=caught_up,
        active_call_ids=list(parsed.active_exec_call_ids),
        issues=issues,
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
    active_exec_call_ids: tuple[str, ...] = ()
    parse_issue_counts: dict[str, int] = field(default_factory=dict)


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
    active_exec_call_ids = parsed.get("active_exec_call_ids", [])
    parse_issue_counts = parsed.get("parse_issue_counts", {})
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
    if not isinstance(active_exec_call_ids, list) or not all(
        isinstance(call_id, str) and call_id for call_id in active_exec_call_ids
    ):
        return _TranscriptParseCheckpoint()
    if not isinstance(parse_issue_counts, dict) or not all(
        isinstance(code, str)
        and code
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 1
        for code, count in parse_issue_counts.items()
    ):
        return _TranscriptParseCheckpoint()
    active_exec_calls = tuple(active_exec_call_ids)
    # Existing JSON checkpoints carry valid parser state but no byte position.
    # Scan their completed prefix once; never reinterpret old rows using new event kinds.
    if byte_offset is None:
        return _TranscriptParseCheckpoint(
            line_offset=line_offset, turn=turn, sequence=sequence,
            saw_content=saw_content, legacy=True,
            history_start_ordinal=history_start_ordinal,
            parent_thread_id=parent_thread_id,
            active_exec_call_ids=active_exec_calls,
            parse_issue_counts=dict(parse_issue_counts),
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
        active_exec_call_ids=active_exec_calls,
        parse_issue_counts=dict(parse_issue_counts),
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
    parse_issue_counts: dict[str, int],
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
            "active_exec_call_ids": state.active_exec_call_ids,
            "parse_issue_counts": parse_issue_counts,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
