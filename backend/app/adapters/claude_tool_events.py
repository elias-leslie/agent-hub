"""Canonical ToolEvent adaptation for Claude SDK tool streams."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters._claude_result_metadata import resolve_result_finish_reason
from app.adapters.base import ProviderError
from app.adapters.claude_utils import extract_block_content, is_thinking_block, is_tool_use_block
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage


def _convert_assistant_message(
    msg: Any,
    tool_start_times: dict[str, float],
) -> list[ToolEvent]:
    """Convert a Claude AssistantMessage into ToolEvent(s)."""
    blocks: list[ToolContentBlock] = []
    for block in msg.content:
        extracted = extract_block_content(block)
        if extracted["type"] == "text":
            blocks.append(ToolContentBlock(type="text", text=str(extracted.get("text") or "")))
        elif extracted["type"] == "thinking":
            thinking_text = str(extracted.get("thinking") or "")
            if thinking_text:
                blocks.append(ToolContentBlock(type="thinking", text=thinking_text))
        elif extracted["type"] == "tool_use":
            tool_id = str(extracted.get("id") or "")
            if tool_id:
                tool_start_times[tool_id] = time.monotonic()
            blocks.append(ToolContentBlock(
                type="tool_use",
                name=str(extracted.get("name") or "unknown"),
                input=extracted.get("input") or {},
                id=tool_id,
            ))
    return [ToolEvent(type="assistant", message=ToolMessage(content=blocks))]


def _convert_user_message(
    msg: Any,
    tool_start_times: dict[str, float],
) -> list[ToolEvent]:
    """Convert a Claude UserMessage (tool results) into ToolEvent(s)."""
    events: list[ToolEvent] = []
    if not hasattr(msg, "content"):
        return events
    for block in msg.content:
        if type(block).__name__ != "ToolResultBlock":
            continue
        tool_use_id = getattr(block, "tool_use_id", "")
        start = tool_start_times.pop(tool_use_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        events.append(ToolEvent(
            type="tool_result",
            content=str(getattr(block, "content", "")),
            tool_use_id=tool_use_id,
            is_error=getattr(block, "is_error", False),
            duration_ms=duration_ms,
        ))
    return events


def _convert_result_message(msg: Any) -> list[ToolEvent]:
    """Convert Claude ResultMessage into a terminal result event."""
    subtype = getattr(msg, "subtype", None)
    finish_reason = resolve_result_finish_reason(msg)
    result_text = getattr(msg, "result", None)
    if isinstance(result_text, str) and result_text.strip():
        return [ToolEvent(type="result", subtype=subtype, result=result_text, finish_reason=finish_reason)]
    return [ToolEvent(type="result", subtype=subtype, result="", finish_reason=finish_reason)]


def _convert_top_level_assistant_block(
    msg: Any,
    tool_start_times: dict[str, float],
) -> ToolContentBlock | None:
    """Convert a top-level Claude thinking/tool_use block into assistant content."""
    if is_thinking_block(msg):
        thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
        if thinking_text:
            return ToolContentBlock(type="thinking", text=thinking_text)
        return None

    if is_tool_use_block(msg):
        tool_id = getattr(msg, "id", "")
        if tool_id:
            tool_start_times[tool_id] = time.monotonic()
        return ToolContentBlock(
            type="tool_use",
            name=getattr(msg, "name", "unknown"),
            input=getattr(msg, "input", {}),
            id=tool_id,
        )

    return None


def _assistant_event(blocks: list[ToolContentBlock]) -> ToolEvent:
    """Build a normalized assistant ToolEvent from buffered content blocks."""
    return ToolEvent(type="assistant", message=ToolMessage(content=list(blocks)))


def adapt_claude_message(
    msg: Any,
    tool_start_times: dict[str, float] | None = None,
) -> list[ToolEvent]:
    """Convert a single Claude SDK message into a list of ToolEvents."""
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, UserMessage

    timing_state = tool_start_times if tool_start_times is not None else {}

    top_level_block = _convert_top_level_assistant_block(msg, timing_state)
    if top_level_block is not None:
        return [_assistant_event([top_level_block])]

    if isinstance(msg, AssistantMessage):
        return _convert_assistant_message(msg, timing_state)

    if isinstance(msg, UserMessage):
        return _convert_user_message(msg, timing_state)

    if isinstance(msg, ResultMessage) or type(msg).__name__ == "ResultMessage":
        return _convert_result_message(msg)

    if type(msg).__name__ == "ErrorMessage":
        return [ToolEvent(type="error", error=getattr(msg, "error", "Unknown error"))]

    return []


async def adapt_claude_stream(
    stream: AsyncIterator[tuple[Any, str]],
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Wrap a Claude complete_with_tools stream, yielding ToolEvents."""
    last_session_id = ""
    pending_assistant_blocks: list[ToolContentBlock] = []
    tool_start_times: dict[str, float] = {}

    def _flush_pending() -> list[tuple[ToolEvent, str]]:
        if not pending_assistant_blocks:
            return []
        event = _assistant_event(pending_assistant_blocks)
        pending_assistant_blocks.clear()
        return [(event, last_session_id)]

    try:
        async for msg, session_id in stream:
            last_session_id = session_id or last_session_id
            pending_block = _convert_top_level_assistant_block(msg, tool_start_times)
            if pending_block is not None:
                pending_assistant_blocks.append(pending_block)
                continue

            events = adapt_claude_message(msg, tool_start_times)
            if pending_assistant_blocks:
                if events and events[0].type == "assistant" and events[0].message is not None:
                    events[0].message.content = [*pending_assistant_blocks, *events[0].message.content]
                    pending_assistant_blocks.clear()
                else:
                    for pending_event in _flush_pending():
                        yield pending_event

            for event in events:
                yield event, session_id

        for pending_event in _flush_pending():
            yield pending_event
    except ProviderError as exc:
        for pending_event in _flush_pending():
            yield pending_event
        yield ToolEvent(type="error", error=str(exc)), last_session_id
    except Exception as exc:
        for pending_event in _flush_pending():
            yield pending_event
        yield ToolEvent(type="error", error=str(exc)), last_session_id
