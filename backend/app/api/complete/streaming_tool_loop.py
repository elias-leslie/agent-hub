"""Tool execution loop for streaming completions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.adapters.base import Message

from .closeout_policy import (
    plan_user_facing_closeout,
)
from .schemas import StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import (
    build_done_sse,
    mirror_stream_tool_result,  # noqa: F401 - compatibility patch point for tests
    mirror_stream_tool_use,  # noqa: F401 - compatibility patch point for tests
    publish_stream_progress,  # noqa: F401 - compatibility patch point for tests
)
from .streaming_runtime_session import iter_runtime_session_sse_with_tools
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

__all__ = [
    "DEFAULT_MAX_TOOL_TURNS",
    "iter_stream_sse_with_tools",
    "sse_for_simple_event",
]


def _create_tool_handler(
    stream_kwargs: dict[str, object],
    project_id: str | None,
    ctx: StreamContext,
) -> object:
    from app.services.tools.tool_handler import create_direct_handler

    return create_direct_handler(
        working_dir=stream_kwargs.get("working_dir"),
        project_id=project_id,
        session_id=ctx.session_id,
    )


def _build_max_turns_error_sse(max_tool_turns: int, seq: int) -> str:
    return f"data: {StreamingChunk(type='error', seq=seq, error=f'Tool execution reached maximum turns ({max_tool_turns})').model_dump_json()}\n\n"


async def _handle_no_unresolved(
    done_event: object,
    turn_text: str,
    pending_calls: list,
    turn: int,
    max_tool_turns: int,
    closeout_recovery_used: bool,
    current_messages: list[Message],
    content_buf: list[str],
    ctx: StreamContext,
) -> tuple[str | None, bool]:
    """Handle a turn where no unresolved tool calls remain.

    Returns (done_sse, should_continue).  When should_continue is True,
    done_sse is None and the caller must set closeout_recovery_used and continue.
    """
    closeout_plan = plan_user_facing_closeout(
        turn_text,
        tool_calls_count=len(pending_calls),
        allow_recovery=turn < max_tool_turns,
        recovery_used=closeout_recovery_used,
    )
    if closeout_plan.action == "recover":
        current_messages.append(Message(role="assistant", content=turn_text))
        current_messages.append(Message(role="user", content=closeout_plan.prompt or ""))
        return None, True
    done_sse = await build_done_sse(
        event=done_event, ctx=ctx,
        accumulated_content=content_buf[0], seq=ctx.next_seq(),
    )
    return done_sse, False


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
    try:
        async for chunk in iter_runtime_session_sse_with_tools(
            adapter,
            messages,
            model,
            temperature,
            stream_kwargs,
            content_buf,
            ctx,
            project_id,
            max_tool_turns,
        ):
            yield chunk
        return
    except NotImplementedError:
        logger.debug("Streaming tool loop falling back to legacy stream-event path")

    handler = _create_tool_handler(stream_kwargs, project_id, ctx)
    current_messages = list(messages)
    closeout_recovery_used = False

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
            done_sse, should_continue = await _handle_no_unresolved(
                done_event, turn_text, pending_calls, turn, max_tool_turns,
                closeout_recovery_used, current_messages, content_buf, ctx,
            )
            if should_continue:
                closeout_recovery_used = True
                continue
            if done_sse is not None:
                yield done_sse
            return
        result_tuples: list[tuple[str, str, str, bool]] = []
        async for sse in iter_unresolved_tools(unresolved, handler, ctx, turn, result_tuples):
            yield sse
        if not result_tuples:
            return
        append_turn_messages(current_messages, turn_text, pending_calls, result_tuples)

    logger.warning("Streaming: reached max tool turns (%d) for session %s", max_tool_turns, ctx.session_id)
    yield _build_max_turns_error_sse(max_tool_turns, ctx.next_seq())
