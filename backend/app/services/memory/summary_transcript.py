"""Transcript building for session summary generation.

Extracts and condenses session events into a compact format suitable
for LLM summarization. Supports two sources:
- SessionEvent objects from PostgreSQL (API sessions)
- JSONL transcript files from Claude Code and Codex
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.services.event_storage import _extract_tool_result_content
from app.services.session_ingestion.adapters.transcript_parsers import parse_transcript_events

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_LINES = 100  # Max lines in condensed transcript
RECENCY_RATIO = 0.7  # 70% recent, 30% early

# JSON object type alias — values are heterogeneous runtime data.
JsonObject = dict[str, object]


class _SessionEventLike(Protocol):
    """Structural protocol matching SessionEvent fields used here."""

    event_type: str
    content: str | None
    tool_name: str | None
    tool_input: JsonObject | None
    tool_output: object | None


def build_condensed_transcript(events: Sequence[_SessionEventLike]) -> str:
    """Build a condensed transcript from session events for summarization."""
    lines: list[str] = []
    for event in events:
        _append_event_line(event, lines)
    return _apply_recency_window(lines)


def _append_event_line(event: _SessionEventLike, lines: list[str]) -> None:
    """Append a formatted line for one event to lines (mutates in place)."""
    if event.event_type == "user_message" and event.content:
        lines.append(f"USER: {event.content[:1000]}")
        return
    if event.event_type == "assistant_message" and event.content:
        lines.append(f"ASSISTANT: {event.content[:500]}")
        return
    if event.event_type == "tool_use" and event.tool_name:
        preview = f" ({str(event.tool_input)[:100]})" if event.tool_input else ""
        lines.append(f"TOOL: {event.tool_name}{preview}")
        return
    if event.event_type == "tool_result" and event.tool_output:
        content = (
            _extract_tool_result_content(event.tool_output)
            if isinstance(event.tool_output, dict)
            else str(event.tool_output)
        )
        if content:
            lines.append(f"RESULT: {content[:200]}")
        return
    if event.event_type == "error" and event.content:
        lines.append(f"ERROR: {event.content[:200]}")


def read_transcript_text(transcript_path: str) -> str:
    """Read raw transcript text from a supported JSONL transcript path."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        logger.warning("Transcript not found or not JSONL: %s", transcript_path)
        return ""
    try:
        return path.read_text()
    except OSError as e:
        logger.warning("Failed to read transcript %s: %s", transcript_path, e)
        return ""


def build_transcript_from_jsonl(transcript_path: str) -> str:
    """Build a condensed transcript from a JSONL transcript file."""
    raw_text = read_transcript_text(transcript_path)
    if not raw_text:
        return ""
    path = Path(transcript_path)
    result = build_condensed_transcript(parse_transcript_events(raw_text.splitlines()))
    if result:
        logger.info("Built transcript: %d lines from %s", len(result.splitlines()), path.name)
    return result


def build_transcript_from_cc_jsonl(transcript_path: str) -> str:
    """Backward-compatible alias for generic JSONL transcript building."""
    return build_transcript_from_jsonl(transcript_path)


def build_condensed_transcript_from_jsonl(jsonl_lines: list[str]) -> str:
    """Build a condensed transcript from supported JSONL transcript lines."""
    events = parse_transcript_events(jsonl_lines)
    return build_condensed_transcript(events)


def _apply_recency_window(lines: list[str]) -> str:
    """Apply recency-biased windowing: 30% early context + 70% recent."""
    if len(lines) <= MAX_TRANSCRIPT_LINES:
        return "\n".join(lines)
    recent_budget = int(MAX_TRANSCRIPT_LINES * RECENCY_RATIO)  # 70 lines
    early_budget = MAX_TRANSCRIPT_LINES - recent_budget  # 30 lines
    split_idx = len(lines) * 3 // 4  # last 25% of transcript is "recent"
    early_lines = lines[:split_idx][:early_budget]
    recent_lines = lines[split_idx:][-recent_budget:]
    return "\n".join([*early_lines, "--- [recent work below] ---", *recent_lines])
