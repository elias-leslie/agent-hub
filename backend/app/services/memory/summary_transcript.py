"""Transcript building for session summary generation.

Extracts and condenses session events into a compact format suitable
for LLM summarization. Supports two sources:
- SessionEvent objects from PostgreSQL (API sessions)
- JSONL transcript files from Claude Code and Codex
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

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
        lines.append(f"RESULT: {str(event.tool_output)[:200]}")
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
    result = build_condensed_transcript_from_jsonl(raw_text.splitlines())
    if result:
        logger.info("Built transcript: %d lines from %s", len(result.splitlines()), path.name)
    return result


def build_transcript_from_cc_jsonl(transcript_path: str) -> str:
    """Backward-compatible alias for generic JSONL transcript building."""
    return build_transcript_from_jsonl(transcript_path)


def build_condensed_transcript_from_jsonl(jsonl_lines: list[str]) -> str:
    """Build a condensed transcript from supported JSONL transcript lines."""
    lines: list[str] = []
    for raw_line in jsonl_lines:
        obj = _parse_jsonl_line(raw_line)
        if obj is None:
            continue
        _append_jsonl_entry_lines(obj, lines)
    return _apply_recency_window(lines) if lines else ""


def _parse_jsonl_line(raw_line: str) -> JsonObject | None:
    """Parse a single JSONL line; return None if malformed."""
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _get_message_content(obj: JsonObject) -> object:
    """Extract the content field from a JSONL message entry."""
    message = obj.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if content is not None else ""


def _append_jsonl_entry_lines(obj: JsonObject, lines: list[str]) -> None:
    """Append transcript lines for one supported JSONL entry."""
    entry_type = obj.get("type")
    if entry_type == "user" and not obj.get("isMeta"):
        _process_user_entry(obj, lines)
        return
    if entry_type == "assistant":
        _process_assistant_entry(obj, lines)
        return
    if entry_type == "response_item":
        _process_codex_response_item(obj.get("payload"), lines)


def _process_user_entry(obj: JsonObject, lines: list[str]) -> None:
    """Extract user message lines from a CC JSONL user entry."""
    content = _get_message_content(obj)
    if isinstance(content, str) and content.strip():
        cleaned = _strip_command_tags(content)
        if cleaned:
            lines.append(f"USER: {cleaned[:1000]}")
        return
    if not isinstance(content, list):
        return
    for block in content:
        _append_user_text_block(block, lines)


def _append_user_text_block(block: object, lines: list[str]) -> None:
    """Append a user text block to lines if it is non-empty text."""
    if not isinstance(block, dict) or block.get("type") != "text":
        return
    raw_text = block.get("text")
    text = raw_text if isinstance(raw_text, str) else ""
    if not text.strip():
        return
    cleaned = _strip_command_tags(text)
    if cleaned:
        lines.append(f"USER: {cleaned[:1000]}")


def _process_assistant_entry(obj: JsonObject, lines: list[str]) -> None:
    """Extract assistant message lines from a CC JSONL assistant entry."""
    content = _get_message_content(obj)
    if isinstance(content, str) and content.strip():
        lines.append(f"ASSISTANT: {content[:500]}")
        return
    if not isinstance(content, list):
        return
    for block in content:
        _append_assistant_block(block, lines)


def _append_assistant_block(block: object, lines: list[str]) -> None:
    """Append an assistant content block (text or tool_use) to lines."""
    if not isinstance(block, dict):
        return
    block_type = block.get("type")
    if block_type == "text":
        raw_text = block.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        if text.strip():
            lines.append(f"ASSISTANT: {text[:500]}")
    elif block_type == "tool_use":
        raw_name = block.get("name")
        tool_name = raw_name if isinstance(raw_name, str) else "unknown"
        raw_input = block.get("input")
        tool_input: JsonObject = raw_input if isinstance(raw_input, dict) else {}
        preview = _tool_input_preview(tool_name, tool_input)
        lines.append(f"TOOL: {tool_name}{preview}")


def _process_codex_response_item(payload: object, lines: list[str]) -> None:
    """Extract transcript lines from a Codex response_item payload."""
    if not isinstance(payload, dict):
        return
    payload_type = payload.get("type")
    if payload_type == "message":
        _process_codex_message_payload(payload, lines)
        return
    if payload_type == "function_call":
        _append_codex_function_call(payload, lines)
        return
    if payload_type == "function_call_output":
        _append_codex_function_call_output(payload, lines)


def _process_codex_message_payload(payload: JsonObject, lines: list[str]) -> None:
    """Extract user and assistant message lines from a Codex message payload."""
    role = payload.get("role")
    content = payload.get("content")
    if not isinstance(content, list):
        return
    prefix = "USER" if role == "user" else "ASSISTANT" if role == "assistant" else None
    if prefix is None:
        return
    for block in content:
        _append_codex_message_block(block, lines, prefix)


def _append_codex_message_block(block: object, lines: list[str], prefix: str) -> None:
    """Append a Codex message content block to transcript lines."""
    if not isinstance(block, dict):
        return
    block_type = block.get("type")
    if block_type not in {"input_text", "output_text", "text"}:
        return
    raw_text = block.get("text")
    text = raw_text if isinstance(raw_text, str) else ""
    if not text.strip():
        return
    cleaned = _strip_command_tags(text) if prefix == "USER" else text.strip()
    if cleaned:
        limit = 1000 if prefix == "USER" else 500
        lines.append(f"{prefix}: {cleaned[:limit]}")


def _append_codex_function_call(payload: JsonObject, lines: list[str]) -> None:
    """Append a Codex tool call entry to transcript lines."""
    raw_name = payload.get("name")
    tool_name = raw_name if isinstance(raw_name, str) else "unknown"
    tool_input = _parse_codex_function_arguments(payload.get("arguments"))
    preview = _tool_input_preview(tool_name, tool_input)
    lines.append(f"TOOL: {tool_name}{preview}")


def _append_codex_function_call_output(payload: JsonObject, lines: list[str]) -> None:
    """Append a Codex tool result entry to transcript lines."""
    raw_output = payload.get("output")
    if isinstance(raw_output, str) and raw_output.strip():
        lines.append(f"RESULT: {raw_output[:200]}")


def _parse_codex_function_arguments(arguments: object) -> JsonObject:
    """Parse Codex function call arguments JSON into a dict when possible."""
    if isinstance(arguments, dict):
        return {str(key): value for key, value in arguments.items()}
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def _strip_command_tags(content: str) -> str:
    """Strip CC command XML tags from user content for cleaner summaries."""
    if content.startswith(("<local-command", "<command-")):
        return ""
    return content.strip()


def _tool_input_preview(tool_name: str, tool_input: JsonObject) -> str:
    """Build compact preview of tool input for transcript."""
    if tool_name in ("Write", "Edit"):
        val = tool_input.get("file_path")
        return f" ({val})" if val else ""
    if tool_name == "Bash":
        val = tool_input.get("command")
        return f" ({str(val)[:100]})" if val else ""
    if tool_name in ("Read", "Glob", "Grep"):
        val = tool_input.get("file_path") or tool_input.get("pattern")
        return f" ({str(val)[:100]})" if val else ""
    if tool_name == "Task":
        val = tool_input.get("description")
        return f" ({str(val)[:80]})" if val else ""
    preview = str(tool_input)[:100] if tool_input else ""
    return f" ({preview})" if preview else ""
