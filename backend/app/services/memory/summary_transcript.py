"""Transcript building for session summary generation.

Extracts and condenses session events into a compact format suitable
for LLM summarization.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_condensed_transcript(events: Sequence[Any]) -> str:
    """Build a condensed transcript from session events for summarization.

    Extracts user messages, assistant messages, tool calls, and errors
    into a compact format. Truncates individual entries and limits total
    output to the last 100 lines.

    Args:
        events: Sequence of SessionEvent objects to process.

    Returns:
        Condensed transcript string with max 100 lines.
    """
    lines: list[str] = []
    for event in events:
        if event.event_type == "user_message" and event.content:
            lines.append(f"USER: {event.content[:500]}")
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

    # Return last 100 lines max to keep within token budget
    return "\n".join(lines[-100:])
