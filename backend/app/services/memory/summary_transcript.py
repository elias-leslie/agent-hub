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

# Max lines in condensed transcript
MAX_TRANSCRIPT_LINES = 100


def build_condensed_transcript(events: Sequence[Any]) -> str:
    """Build a condensed transcript from session events for summarization.

    Extracts user messages, assistant messages, tool calls, and errors
    into a compact format. Truncates individual entries and limits total
    output to the last MAX_TRANSCRIPT_LINES lines.

    Args:
        events: Sequence of SessionEvent objects to process.

    Returns:
        Condensed transcript string with max 100 lines.
    """
    lines: list[str] = []
    for event in events:
        if event.event_type == "user_message" and event.content:
            lines.append(f"USER: {event.content[:1000]}")
        elif event.event_type == "assistant_message" and event.content:
            lines.append(f"ASSISTANT: {event.content[:500]}")
        elif event.event_type == "tool_use" and event.tool_name:
            input_preview = ""
            if event.tool_input:
                input_str = str(event.tool_input)
                input_preview = f" ({input_str[:100]})"
            lines.append(f"TOOL: {event.tool_name}{input_preview}")
        elif event.event_type == "tool_result" and event.tool_output:
            output_str = str(event.tool_output)
            lines.append(f"RESULT: {output_str[:200]}")
        elif event.event_type == "error" and event.content:
            lines.append(f"ERROR: {event.content[:200]}")

    return "\n".join(lines[-MAX_TRANSCRIPT_LINES:])


def build_transcript_from_cc_jsonl(transcript_path: str) -> str:
    """Build a condensed transcript from a Claude Code JSONL transcript file.

    Reads the file and delegates to build_condensed_transcript_from_jsonl
    for parsing.

    Args:
        transcript_path: Absolute path to the CC .jsonl transcript file.

    Returns:
        Condensed transcript string, or empty string if file can't be read.
    """
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
    """Build a condensed transcript from CC JSONL lines.

    Parses the CC JSONL format which contains user messages, assistant
    messages (text + tool_use blocks), and progress events. Extracts
    high-signal content for summarization.

    Args:
        jsonl_lines: Raw JSONL lines from a CC transcript file.

    Returns:
        Condensed transcript string with max MAX_TRANSCRIPT_LINES lines.
    """
    lines: list[str] = []

    for raw_line in jsonl_lines:
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        entry_type = obj.get("type")

        if entry_type == "user" and not obj.get("isMeta"):
            content = obj.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                cleaned = _strip_command_tags(content)
                if cleaned:
                    lines.append(f"USER: {cleaned[:1000]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text.strip():
                            cleaned = _strip_command_tags(text)
                            if cleaned:
                                lines.append(f"USER: {cleaned[:1000]}")

        elif entry_type == "assistant":
            content = obj.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                lines.append(f"ASSISTANT: {content[:500]}")
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text" and block.get("text", "").strip():
                        lines.append(f"ASSISTANT: {block['text'][:500]}")
                    elif block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        preview = _tool_input_preview(tool_name, tool_input)
                        lines.append(f"TOOL: {tool_name}{preview}")

    if not lines:
        return ""

    return "\n".join(lines[-MAX_TRANSCRIPT_LINES:])


def _strip_command_tags(content: str) -> str:
    """Strip CC command XML tags from user content for cleaner summaries."""
    # Skip meta messages (command outputs, local command caveats)
    if content.startswith("<local-command"):
        return ""
    if content.startswith("<command-"):
        return ""
    return content.strip()


def _tool_input_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build compact preview of tool input for transcript."""
    if tool_name in ("Write", "Edit"):
        fp = tool_input.get("file_path", "")
        if fp:
            return f" ({fp})"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd:
            return f" ({cmd[:100]})"
    elif tool_name in ("Read", "Glob", "Grep"):
        # Include file path or pattern for context
        fp = tool_input.get("file_path", tool_input.get("pattern", ""))
        if fp:
            return f" ({fp[:100]})"
    elif tool_name == "Task":
        desc = tool_input.get("description", "")
        if desc:
            return f" ({desc[:80]})"

    # Generic fallback
    preview = str(tool_input)[:100] if tool_input else ""
    return f" ({preview})" if preview else ""
