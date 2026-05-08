"""Canonical ToolEvent adaptation for StreamEvent-based providers.

OpenAI-compatible adapters and the Codex adapter already expose tool-capable
turns as StreamEvent sequences. This module converts those streams into the
canonical ToolEvent format used by the shared tool execution pipeline.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage


def adapt_stream_event(
    event: StreamEvent,
    tool_start_times: dict[str, float] | None = None,
) -> ToolEvent | None:
    """Convert a single StreamEvent to a ToolEvent."""
    timing_state = tool_start_times if tool_start_times is not None else {}

    if event.type == "tool_use":
        tool_id = getattr(event, "tool_id", "") or ""
        if tool_id:
            timing_state[tool_id] = time.monotonic()
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
        start = timing_state.pop(tool_id, None)
        duration_ms = getattr(event, "duration_ms", None)
        if duration_ms is None and start is not None:
            duration_ms = int((time.monotonic() - start) * 1000)
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
            result="",
            finish_reason=getattr(event, "finish_reason", None),
        )

    if event.type == "error":
        return ToolEvent(
            type="error",
            error=getattr(event, "error", "Unknown error") or "Unknown error",
        )

    return None


def create_tool_handler(
    working_dir: str | None,
    project_id: str | None = None,
    session_id: str | None = None,
    agent_slug: str | None = None,
    tool_catalog: list[dict[str, Any]] | None = None,
) -> Any:
    """Create an async tool_handler callback for StreamEvent-based providers."""
    from app.services.tools.base import ToolCall, ToolResult
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir,
        project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        tool_catalog=tool_catalog,
    )

    async def tool_handler(tool_name: str, tool_input: dict[str, Any]) -> ToolResult:
        tool_call = ToolCall(
            id=f"openai_{tool_name}_{id(tool_input)}",
            name=tool_name,
            input=tool_input,
        )
        result = await handler.execute(tool_call)
        return result

    return tool_handler


async def adapt_openai_stream(
    adapter: Any,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_turns: int = 20,
    project_id: str | None = None,
    session_id: str | None = None,
    agent_slug: str | None = None,
    tool_catalog: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Run a StreamEvent-based provider's complete_with_tools and yield ToolEvents."""
    handler = create_tool_handler(
        working_dir,
        project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        tool_catalog=tool_catalog,
    )
    tool_start_times: dict[str, float] = {}

    async for stream_event in adapter.complete_with_tools(
        messages=messages,
        model=model,
        tools=tools,
        tool_handler=handler,
        max_turns=max_turns,
    ):
        tool_event = adapt_stream_event(stream_event, tool_start_times)
        if tool_event is not None:
            yield tool_event, ""
