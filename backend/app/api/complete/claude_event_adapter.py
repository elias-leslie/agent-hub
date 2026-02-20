"""Adapt Claude Agent SDK messages to unified ToolEvent format.

Claude's complete_with_tools() yields (sdk_message, session_id) tuples
where sdk_message can be AssistantMessage, UserMessage, ThinkingBlock,
or ToolUseBlock. This module converts each into ToolEvent objects that
the unified tool_event_processor can handle.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage

# Track tool start times for duration_ms calculation
_tool_start_times: dict[str, float] = {}


def _is_thinking_block(msg: Any) -> bool:
    return type(msg).__name__ == "ThinkingBlock" or (
        hasattr(msg, "type") and msg.type == "thinking"
    )


def _is_tool_use_block(msg: Any) -> bool:
    return type(msg).__name__ == "ToolUseBlock" or (
        hasattr(msg, "type") and msg.type == "tool_use"
    )


def _convert_assistant_message(msg: Any) -> list[ToolEvent]:
    """Convert a Claude AssistantMessage into ToolEvent(s)."""
    blocks: list[ToolContentBlock] = []
    for block in msg.content:
        if hasattr(block, "text") and type(block).__name__ == "TextBlock":
            blocks.append(ToolContentBlock(type="text", text=block.text))
        elif _is_thinking_block(block):
            thinking_text = getattr(block, "thinking", "") or getattr(block, "text", "")
            if thinking_text:
                blocks.append(ToolContentBlock(type="thinking", text=thinking_text))
        elif _is_tool_use_block(block):
            tool_id = getattr(block, "id", "")
            if tool_id:
                _tool_start_times[tool_id] = time.monotonic()
            blocks.append(ToolContentBlock(
                type="tool_use",
                name=getattr(block, "name", "unknown"),
                input=getattr(block, "input", {}),
                id=tool_id,
            ))
    return [ToolEvent(type="assistant", message=ToolMessage(content=blocks))]


def _convert_user_message(msg: Any) -> list[ToolEvent]:
    """Convert a Claude UserMessage (tool results) into ToolEvent(s)."""
    events: list[ToolEvent] = []
    if not hasattr(msg, "content"):
        return events
    for block in msg.content:
        if type(block).__name__ != "ToolResultBlock":
            continue
        tool_use_id = getattr(block, "tool_use_id", "")
        start = _tool_start_times.pop(tool_use_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        events.append(ToolEvent(
            type="tool_result",
            content=str(getattr(block, "content", "")),
            tool_use_id=tool_use_id,
            is_error=getattr(block, "is_error", False),
            duration_ms=duration_ms,
        ))
    return events


def adapt_claude_message(msg: Any) -> list[ToolEvent]:
    """Convert a single Claude SDK message into a list of ToolEvents.

    Args:
        msg: A Claude SDK message (AssistantMessage, UserMessage,
             ThinkingBlock, or ToolUseBlock)

    Returns:
        List of ToolEvent objects (may be empty for unrecognized types)
    """
    from claude_agent_sdk.types import AssistantMessage, UserMessage

    # Top-level thinking block (not inside AssistantMessage)
    if _is_thinking_block(msg):
        thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
        if thinking_text:
            return [ToolEvent(
                type="assistant",
                message=ToolMessage(content=[
                    ToolContentBlock(type="thinking", text=thinking_text),
                ]),
            )]
        return []

    # Top-level tool use block
    if _is_tool_use_block(msg):
        tool_id = getattr(msg, "id", "")
        if tool_id:
            _tool_start_times[tool_id] = time.monotonic()
        return [ToolEvent(
            type="assistant",
            message=ToolMessage(content=[
                ToolContentBlock(
                    type="tool_use",
                    name=getattr(msg, "name", "unknown"),
                    input=getattr(msg, "input", {}),
                    id=tool_id,
                ),
            ]),
        )]

    if isinstance(msg, AssistantMessage):
        return _convert_assistant_message(msg)

    if isinstance(msg, UserMessage):
        return _convert_user_message(msg)

    return []


async def adapt_claude_stream(
    stream: AsyncIterator[tuple[Any, str]],
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Wrap a Claude complete_with_tools stream, yielding ToolEvents.

    Args:
        stream: AsyncIterator of (sdk_message, session_id) tuples

    Yields:
        (ToolEvent, session_id) tuples
    """
    async for msg, session_id in stream:
        for event in adapt_claude_message(msg):
            yield event, session_id
