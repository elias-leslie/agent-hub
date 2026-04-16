"""Per-turn tool execution and event collection for the streaming tool loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import Message

from .schemas import StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import (
    log_tool_audit,
    mirror_stream_tool_result,
    mirror_stream_tool_use,
    publish_stream_progress,
    should_publish_stream_progress,
)
from .streaming_tool_messages import (
    build_assistant_content_blocks,
    build_tool_result_blocks,
    sse_for_simple_event,
)

if TYPE_CHECKING:
    from app.adapters.types import StreamEvent
    from app.services.tools.base import ToolHandler

logger = logging.getLogger(__name__)

_TOOL_HEARTBEAT_INTERVAL_S = 10


async def _iter_tool_execution(
    tc_event: StreamEvent,
    handler: ToolHandler,
    ctx: StreamContext,
    result_out: list[tuple[str, str, str, bool]],
) -> AsyncIterator[str]:
    """Execute one tool call, yielding SSE strings (start, heartbeats, result).

    If the user has cancelled, yields a ``cancelled`` SSE and returns immediately
    without appending to ``result_out``.
    """
    if ctx.cancel_event and ctx.cancel_event.is_set():
        logger.info("Streaming: user cancelled tool execution for session %s", ctx.session_id)
        cancelled_chunk = StreamingChunk(
            type="cancelled", seq=ctx.next_seq(),
            session_id=ctx.session_id, provider=ctx.provider, model=ctx.model,
        )
        yield f"data: {cancelled_chunk.model_dump_json()}\n\n"
        return

    from app.services.tools.base import ToolCall

    tool_name = tc_event.tool_name or ""
    tool_call = ToolCall(id=tc_event.tool_id or "", name=tool_name, input=tc_event.tool_input or {})

    await mirror_stream_tool_use(ctx, tool_name, tc_event.tool_input or {})
    yield f"data: {StreamingChunk(type='tool_start', seq=ctx.next_seq(), tool_id=tool_call.id, tool_name=tool_name).model_dump_json()}\n\n"

    exec_task = asyncio.create_task(handler.execute(tool_call))
    while not exec_task.done():
        done, _ = await asyncio.wait({exec_task}, timeout=_TOOL_HEARTBEAT_INTERVAL_S)
        if not done:
            yield ": heartbeat\n\n"
    result = exec_task.result()

    from app.services.tools.tool_handler import SENSITIVE_TOOLS

    sensitivity = SENSITIVE_TOOLS.get(tool_name)
    if sensitivity:
        log_tool_audit(
            session_id=ctx.session_id, tool_name=tool_name,
            tool_input=tc_event.tool_input or {}, result_content=result.content,
            is_error=result.is_error, duration_ms=result.duration_ms,
            sensitivity=sensitivity, agent_id=ctx.agent_used,
        )

    status = "error" if result.is_error else "complete"
    await mirror_stream_tool_result(
        ctx,
        tool_call.name,
        result.content,
        duration_ms=result.duration_ms,
        is_error=result.is_error,
    )
    yield f"data: {StreamingChunk(type='tool_result', seq=ctx.next_seq(), tool_id=result.tool_use_id, tool_result=result.content, tool_status=status).model_dump_json()}\n\n"
    result_out.append((result.tool_use_id, tool_call.name, result.content, result.is_error))


async def collect_turn_events(
    adapter: object,
    current_messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
) -> tuple[list[str], list[StreamEvent], set[str], str, object | None]:
    """Stream one turn and collect: sse_parts, tool_calls, resolved_ids, turn_text, done_event."""
    ctx.reset_progress_cursor()
    sse_parts: list[str] = []
    pending_tool_calls: list[StreamEvent] = []
    resolved_tool_ids: set[str] = set()
    turn_text = ""
    done_event: object | None = None

    async for event in adapter.stream(  # type: ignore[attr-defined]
        messages=current_messages, model=model,
        max_tokens=max_tokens, temperature=temperature, **stream_kwargs,
    ):
        event_type = getattr(event, "type", None)
        if event_type == "done":
            done_event = event
            continue
        if event_type == "tool_use":
            pending_tool_calls.append(event)
        if event_type == "tool_result" and getattr(event, "tool_id", None):
            resolved_tool_ids.add(event.tool_id)
        if event_type == "content":
            turn_text += getattr(event, "content", None) or ""
        sse = sse_for_simple_event(event, content_buf, ctx)
        if sse is not None:
            sse_parts.append(sse)
        if event_type == "content" and should_publish_stream_progress(ctx, turn_text):
            await publish_stream_progress(ctx, turn_text)

    return sse_parts, pending_tool_calls, resolved_tool_ids, turn_text, done_event


async def iter_unresolved_tools(
    unresolved: list[StreamEvent],
    handler: ToolHandler,
    ctx: StreamContext,
    turn: int,
    result_tuples_out: list[tuple[str, str, str, bool]],
) -> AsyncIterator[str]:
    """Yield SSE strings while executing unresolved tools.

    Tool results are appended to ``result_tuples_out``.  If the user cancelled,
    ``result_tuples_out`` will be empty when this generator finishes.
    """
    logger.info(
        "Streaming turn %d: executing %d tool(s) for session %s",
        turn, len(unresolved), ctx.session_id,
    )
    for tc_event in unresolved:
        prev_len = len(result_tuples_out)
        async for sse in _iter_tool_execution(tc_event, handler, ctx, result_tuples_out):
            yield sse
        if len(result_tuples_out) == prev_len:
            return


def append_turn_messages(
    current_messages: list[Message],
    turn_text: str,
    pending_tool_calls: list[StreamEvent],
    result_tuples: list[tuple[str, str, str, bool]],
) -> None:
    """Append assistant + user tool-result messages for the next turn."""
    current_messages.append(
        Message(role="assistant", content=build_assistant_content_blocks(turn_text, pending_tool_calls))
    )
    current_messages.append(
        Message(role="user", content=build_tool_result_blocks(result_tuples))
    )
