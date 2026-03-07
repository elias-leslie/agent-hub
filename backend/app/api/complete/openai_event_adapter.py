"""Adapt OpenAI-compatible adapter tool calling to unified ToolEvent format.

OpenAI-compat adapters' complete_with_tools() yields StreamEvent objects
and requires a tool_handler callback. This module bridges the gap by:
1. Creating a tool_handler from the DirectToolExecutor
2. Converting yielded StreamEvents to ToolEvent objects
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage

# Track tool start times for duration_ms calculation
_tool_start_times: dict[str, float] = {}


def adapt_stream_event(event: StreamEvent) -> ToolEvent | None:
    """Convert a single StreamEvent to a ToolEvent.

    Args:
        event: StreamEvent from OpenAI-compat adapter

    Returns:
        ToolEvent or None if the event type is not relevant
    """
    if event.type == "tool_use":
        tool_id = getattr(event, "tool_id", "") or ""
        if tool_id:
            _tool_start_times[tool_id] = time.monotonic()
        return ToolEvent(
            type="assistant",
            message=ToolMessage(content=[
                ToolContentBlock(
                    type="tool_use",
                    name=getattr(event, "tool_name", "unknown") or "unknown",
                    input=getattr(event, "tool_input", {}) or {},
                    id=tool_id,
                ),
            ]),
        )

    if event.type == "tool_result":
        tool_id = getattr(event, "tool_id", "") or ""
        start = _tool_start_times.pop(tool_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        is_error = bool(getattr(event, "is_error", False) or getattr(event, "error", None))
        return ToolEvent(
            type="tool_result",
            content=getattr(event, "content", "") or "",
            tool_use_id=tool_id,
            is_error=is_error,
            duration_ms=duration_ms,
        )

    if event.type == "content":
        text = getattr(event, "content", "") or ""
        if text:
            return ToolEvent(
                type="assistant",
                message=ToolMessage(content=[
                    ToolContentBlock(type="text", text=text),
                ]),
            )
        return None

    if event.type == "done":
        return ToolEvent(
            type="result",
            subtype="success",
            result="",  # Content already yielded via "content" events
        )

    if event.type == "error":
        return ToolEvent(
            type="error",
            error=getattr(event, "error", "Unknown error") or "Unknown error",
        )

    return None


def create_tool_handler(
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    project_id: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Create an async tool_handler callback for OpenAI-compat adapters.

    Returns an async function with signature ``(tool_name, tool_input) -> str``
    that uses DirectToolExecutor for tool execution.
    """
    from app.services.tools.base import ToolCall
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir,
        permission_config,
        project_id,
        session_id=session_id,
    )

    async def tool_handler(tool_name: str, tool_input: dict[str, Any]) -> str:
        tool_call = ToolCall(id=f"openai_{tool_name}_{id(tool_input)}", name=tool_name, input=tool_input)
        result = await handler.execute(tool_call)
        return result.content

    return tool_handler


async def adapt_openai_stream(
    adapter: Any,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    max_turns: int = 20,
    project_id: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Run an OpenAI-compat adapter's complete_with_tools and yield ToolEvents.

    Args:
        adapter: OpenAI-compatible adapter instance
        messages: Conversation messages
        model: Model identifier
        tools: Tool definitions
        working_dir: Working directory for tool execution
        permission_config: Permission configuration
        max_turns: Maximum tool execution turns
        project_id: Project ID for agent consultation

    Yields:
        (ToolEvent, session_id) tuples (session_id is empty for OpenAI-compat)
    """
    handler = create_tool_handler(
        working_dir,
        permission_config,
        project_id,
        session_id=session_id,
    )

    async for stream_event in adapter.complete_with_tools(
        messages=messages,
        model=model,
        tools=tools,
        tool_handler=handler,
        max_turns=max_turns,
    ):
        tool_event = adapt_stream_event(stream_event)
        if tool_event is not None:
            yield tool_event, ""
