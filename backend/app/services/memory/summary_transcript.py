"""Transcript building for session summary generation.

Extracts and condenses session events into a compact format suitable
for LLM summarization. Supports two sources:
- SessionEvent objects from PostgreSQL (API sessions)
- CC JSONL transcript files (Claude Code sessions)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_LINES = 100  # Max lines in condensed transcript
RECENCY_RATIO = 0.7  # 70% recent, 30% early


def build_condensed_transcript(events: Sequence[Any]) -> str:
    """Build a condensed transcript from session events for summarization."""
    lines: list[str] = []
    for event in events:
        if event.event_type == "user_message" and event.content:
            lines.append(f"USER: {event.content[:1000]}")
        elif event.event_type == "assistant_message" and event.content:
            lines.append(f"ASSISTANT: {event.content[:500]}")
        elif event.event_type == "tool_use" and event.tool_name:
            preview = f" ({str(event.tool_input)[:100]})" if event.tool_input else ""
            lines.append(f"TOOL: {event.tool_name}{preview}")
        elif event.event_type == "tool_result" and event.tool_output:
            lines.append(f"RESULT: {str(event.tool_output)[:200]}")
        elif event.event_type == "error" and event.content:
            lines.append(f"ERROR: {event.content[:200]}")
    return _apply_recency_window(lines)


def build_transcript_from_cc_jsonl(transcript_path: str) -> str:
    """Build a condensed transcript from a Claude Code JSONL transcript file."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        logger.warning("CC transcript not found or not JSONL: %s", transcript_path)
        return ""
    try:
        raw_lines = path.read_text().splitlines()
    except OSError as e:
        logger.warning("Failed to read CC transcript %s: %s", transcript_path, e)
        return ""
    result = build_condensed_transcript_from_jsonl(raw_lines)
    if result:
        logger.info("Built CC transcript: %d lines from %s", len(result.splitlines()), path.name)
    return result


def build_condensed_transcript_from_jsonl(jsonl_lines: list[str]) -> str:
    """Build a condensed transcript from CC JSONL lines."""
    lines: list[str] = []
    for raw_line in jsonl_lines:
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        entry_type = obj.get("type")
        if entry_type == "user" and not obj.get("isMeta"):
            _process_user_entry(obj, lines)
        elif entry_type == "assistant":
            _process_assistant_entry(obj, lines)
    return _apply_recency_window(lines) if lines else ""


def _process_user_entry(obj: dict[str, Any], lines: list[str]) -> None:
    """Extract user message lines from a CC JSONL user entry."""
    content = obj.get("message", {}).get("content", "")
    if isinstance(content, str) and content.strip():
        cleaned = _strip_command_tags(content)
        if cleaned:
            lines.append(f"USER: {cleaned[:1000]}")
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        cleaned = _strip_command_tags(text) if text.strip() else ""
        if cleaned:
            lines.append(f"USER: {cleaned[:1000]}")


def _process_assistant_entry(obj: dict[str, Any], lines: list[str]) -> None:
    """Extract assistant message lines from a CC JSONL assistant entry."""
    content = obj.get("message", {}).get("content", "")
    if isinstance(content, str) and content.strip():
        lines.append(f"ASSISTANT: {content[:500]}")
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and block.get("text", "").strip():
            lines.append(f"ASSISTANT: {block['text'][:500]}")
        elif block_type == "tool_use":
            tool_name = block.get("name", "unknown")
            preview = _tool_input_preview(tool_name, block.get("input", {}))
            lines.append(f"TOOL: {tool_name}{preview}")


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
    if content.startswith("<local-command") or content.startswith("<command-"):
        return ""
    return content.strip()


def _tool_input_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build compact preview of tool input for transcript."""
    if tool_name in ("Write", "Edit"):
        val = tool_input.get("file_path", "")
        return f" ({val})" if val else ""
    if tool_name == "Bash":
        val = tool_input.get("command", "")
        return f" ({val[:100]})" if val else ""
    if tool_name in ("Read", "Glob", "Grep"):
        val = tool_input.get("file_path", tool_input.get("pattern", ""))
        return f" ({val[:100]})" if val else ""
    if tool_name == "Task":
        val = tool_input.get("description", "")
        return f" ({val[:80]})" if val else ""
    preview = str(tool_input)[:100] if tool_input else ""
    return f" ({preview})" if preview else ""
