"""Tool execution loop for streaming completions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.adapters.base import Message

from .schemas import StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import build_done_sse
from .streaming_tool_executor import (
    append_turn_messages,
    collect_turn_events,
    iter_unresolved_tools,
)
from .streaming_tool_messages import sse_for_simple_event

logger = logging.getLogger(__name__)

# Match CompletionRequest.max_turns default; shared tool budget resolution lifts
# low values to the minimum viable tool loop when tools are actually enabled.
DEFAULT_MAX_TOOL_TURNS = 1
_EMPTY_FINAL_RESPONSE_MSG = (
    "<system-final-response>"
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. "
    "If no changes were needed, say so plainly. "
    "If changes were made, summarize the exact changes and evidence. "
    "Do not call more tools unless a missing fact blocks the response."
    "</system-final-response>"
)

__all__ = [
    "DEFAULT_MAX_TOOL_TURNS",
    "iter_stream_sse_with_tools",
    "sse_for_simple_event",
]


async def iter_stream_sse_with_tools(
    adapter: object,
    messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
    project_id: str | None,
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
) -> AsyncIterator[str]:
    """Yield SSE strings with provider-agnostic tool execution loop."""
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir=stream_kwargs.get("working_dir"),
        project_id=project_id,
        session_id=ctx.session_id,
    )
    current_messages = list(messages)
    empty_closeout_used = False

    for turn in range(1, max_tool_turns + 1):
        turn_sses, pending_calls, resolved_ids, turn_text, done_event = await collect_turn_events(
            adapter, current_messages, model, max_tokens,
            temperature, stream_kwargs, content_buf, ctx,
        )
        for part in turn_sses:
            yield part
        if done_event is None:
            return
        unresolved = [tc for tc in pending_calls if tc.tool_id not in resolved_ids]
        if not unresolved:
            if (
                not content_buf[0].strip()
                and not empty_closeout_used
                and turn < max_tool_turns
            ):
                current_messages.append(Message(role="assistant", content=turn_text))
                current_messages.append(Message(role="user", content=_EMPTY_FINAL_RESPONSE_MSG))
                empty_closeout_used = True
                continue
            yield await build_done_sse(
                event=done_event, ctx=ctx,
                accumulated_content=content_buf[0], seq=ctx.next_seq(),
            )
            return
        result_tuples: list[tuple[str, str, str, bool]] = []
        async for sse in iter_unresolved_tools(unresolved, handler, ctx, turn, result_tuples):
            yield sse
        if not result_tuples:
            return
        append_turn_messages(current_messages, turn_text, pending_calls, result_tuples)

    logger.warning("Streaming: reached max tool turns (%d) for session %s", max_tool_turns, ctx.session_id)
    yield f"data: {StreamingChunk(type='error', seq=ctx.next_seq(), error=f'Tool execution reached maximum turns ({max_tool_turns})').model_dump_json()}\n\n"
