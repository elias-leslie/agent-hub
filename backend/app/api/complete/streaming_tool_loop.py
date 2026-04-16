"""Tool execution loop for streaming completions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from app.adapters.base import Message

from .closeout_policy import (
    append_closeout_turn,
    build_tool_closeout_fallback,
    plan_user_facing_closeout,
)
from .schemas import StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import (
    build_done_sse,
    mirror_stream_tool_result,
    mirror_stream_tool_use,
    publish_stream_progress,
    should_publish_stream_progress,
)
from .streaming_tool_executor import (
    append_turn_messages,
    collect_turn_events,
    iter_unresolved_tools,
)
from .streaming_tool_messages import sse_for_simple_event
from .tool_event_processor import _summarize_tool_result

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


async def _yield_runtime_text_sse(
    text: str,
    *,
    content_buf: list[str],
    ctx: StreamContext,
) -> AsyncIterator[str]:
    if not text:
        return
    content_buf[0] += text
    yield f"data: {StreamingChunk(type='content', seq=ctx.next_seq(), content=text).model_dump_json()}\n\n"
    if should_publish_stream_progress(ctx, content_buf[0]):
        await publish_stream_progress(ctx, content_buf[0])


async def _emit_runtime_done(
    *,
    finish_reason: str | None,
    content_buf: list[str],
    ctx: StreamContext,
) -> str:
    return await build_done_sse(
        event=SimpleNamespace(
            input_tokens=0,
            output_tokens=0,
            finish_reason=finish_reason,
        ),
        ctx=ctx,
        accumulated_content=content_buf[0],
        seq=ctx.next_seq(),
    )


async def _attempt_runtime_closeout_recovery(
    *,
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    working_dir: str | None,
    current_content: str,
    tool_result_summaries: list[str],
) -> tuple[str | None, bool]:
    recovery_plan = plan_user_facing_closeout(
        current_content,
        tool_calls_count=len(tool_result_summaries),
        allow_recovery=True,
        recovery_used=False,
        tool_result_summaries=tool_result_summaries,
    )
    if recovery_plan.action != "recover" or not recovery_plan.prompt:
        return current_content, False

    recovery_messages = list(messages)
    append_closeout_turn(
        recovery_messages,
        None,
        current_content,
        recovery_plan.prompt,
    )
    try:
        result = await adapter.complete(
            messages=recovery_messages,
            model=model,
            max_tokens=None,
            temperature=temperature,
            working_dir=working_dir,
        )
    except Exception:
        logger.warning("Streaming tool closeout recovery failed", exc_info=True)
        return None, True

    if getattr(result, "tool_calls", None):
        logger.warning("Streaming tool closeout recovery requested tools; falling back")
        return result.content, True
    return result.content, False


async def _iter_runtime_session_sse_with_tools(
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
    project_id: str | None,
    max_tool_turns: int,
) -> AsyncIterator[str]:
    start_tool_session = getattr(adapter, "start_tool_session", None)
    if start_tool_session is None:
        raise NotImplementedError("Adapter does not expose start_tool_session")

    runtime_session = await start_tool_session(
        messages=messages,
        model=model,
        tools=stream_kwargs.get("tools"),
        working_dir=stream_kwargs.get("working_dir"),
        max_turns=max_tool_turns,
        project_id=project_id,
        session_id=ctx.session_id,
        agent_slug=ctx.agent_used,
        tool_catalog=stream_kwargs.get("tools"),
    )
    tool_names_by_id: dict[str, str] = {}
    tool_result_summaries: list[str] = []
    terminal_event_seen = False

    async def _yield_runtime_fallback_done(
        *,
        finish_reason: str | None,
    ) -> AsyncIterator[str]:
        if not tool_result_summaries:
            return
        fallback_content = build_tool_closeout_fallback(content_buf[0], tool_result_summaries)
        if fallback_content != content_buf[0]:
            content_buf[0] = fallback_content
            yield f"data: {StreamingChunk(type='content', seq=ctx.next_seq(), content=fallback_content).model_dump_json()}\n\n"
            await publish_stream_progress(ctx, content_buf[0])
        yield await _emit_runtime_done(
            finish_reason=finish_reason,
            content_buf=content_buf,
            ctx=ctx,
        )

    try:
        async for event, _provider_session_id in runtime_session.events():
            event_type = getattr(event, "type", None)

            if event_type == "assistant" and getattr(event, "message", None) is not None:
                blocks = getattr(event.message, "content", []) or []
                for block in blocks:
                    block_type = getattr(block, "type", None)
                    if block_type == "text":
                        async for chunk in _yield_runtime_text_sse(
                            getattr(block, "text", "") or "",
                            content_buf=content_buf,
                            ctx=ctx,
                        ):
                            yield chunk
                    elif block_type == "thinking":
                        thinking_text = getattr(block, "text", "") or ""
                        if thinking_text:
                            yield f"data: {StreamingChunk(type='thinking', seq=ctx.next_seq(), content=thinking_text).model_dump_json()}\n\n"
                    elif block_type == "tool_use":
                        tool_id = getattr(block, "id", "") or ""
                        tool_name = getattr(block, "name", "") or "unknown"
                        tool_input = getattr(block, "input", None) or {}
                        if tool_id:
                            tool_names_by_id[tool_id] = tool_name
                        await mirror_stream_tool_use(ctx, tool_name, tool_input)
                        tool_use_chunk = StreamingChunk(
                            type="tool_use",
                            seq=ctx.next_seq(),
                            tool_id=tool_id or None,
                            tool_name=tool_name,
                            tool_input=tool_input,
                        )
                        yield f"data: {tool_use_chunk.model_dump_json()}\n\n"
                continue

            if event_type == "tool_result":
                tool_content = getattr(event, "content", "") or ""
                tool_id = getattr(event, "tool_use_id", None)
                tool_name = tool_names_by_id.get(str(tool_id or ""), str(tool_id or "tool"))
                is_error = bool(getattr(event, "is_error", False))
                summary = _summarize_tool_result(tool_name, tool_content, is_error)
                if summary:
                    tool_result_summaries.append(summary)
                await mirror_stream_tool_result(
                    ctx,
                    tool_name,
                    tool_content,
                    duration_ms=getattr(event, "duration_ms", None),
                    is_error=is_error,
                )
                tool_result_chunk = StreamingChunk(
                    type="tool_result",
                    seq=ctx.next_seq(),
                    tool_id=tool_id,
                    tool_result=tool_content,
                    tool_status="error" if is_error else "complete",
                )
                yield f"data: {tool_result_chunk.model_dump_json()}\n\n"
                continue

            if event_type == "result":
                terminal_event_seen = True
                final_text = getattr(event, "result", "") or ""
                if final_text:
                    current = content_buf[0]
                    if not current:
                        async for chunk in _yield_runtime_text_sse(final_text, content_buf=content_buf, ctx=ctx):
                            yield chunk
                    elif final_text.startswith(current):
                        suffix = final_text[len(current):]
                        if suffix:
                            async for chunk in _yield_runtime_text_sse(suffix, content_buf=content_buf, ctx=ctx):
                                yield chunk
                closeout_plan = plan_user_facing_closeout(
                    final_text or content_buf[0],
                    tool_calls_count=len(tool_result_summaries),
                    allow_recovery=True,
                    recovery_used=False,
                    tool_result_summaries=tool_result_summaries,
                )
                if closeout_plan.action == "recover":
                    recovered_text, recovery_failed = await _attempt_runtime_closeout_recovery(
                        adapter=adapter,
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        working_dir=stream_kwargs.get("working_dir"),
                        current_content=final_text or content_buf[0],
                        tool_result_summaries=tool_result_summaries,
                    )
                    final_text = recovered_text or final_text or content_buf[0]
                    if not recovery_failed and final_text:
                        current = content_buf[0]
                        if not current:
                            async for chunk in _yield_runtime_text_sse(final_text, content_buf=content_buf, ctx=ctx):
                                yield chunk
                        elif final_text.startswith(current):
                            suffix = final_text[len(current):]
                            if suffix:
                                async for chunk in _yield_runtime_text_sse(suffix, content_buf=content_buf, ctx=ctx):
                                    yield chunk
                        elif final_text != current:
                            async for chunk in _yield_runtime_text_sse(
                                f"\n\n{final_text}",
                                content_buf=content_buf,
                                ctx=ctx,
                            ):
                                yield chunk
                    closeout_plan = plan_user_facing_closeout(
                        final_text,
                        tool_calls_count=len(tool_result_summaries),
                        allow_recovery=False,
                        recovery_used=True,
                        tool_result_summaries=tool_result_summaries,
                    )
                if closeout_plan.action == "fallback":
                    async for chunk in _yield_runtime_fallback_done(
                        finish_reason=getattr(event, "finish_reason", None),
                    ):
                        yield chunk
                    return
                yield await _emit_runtime_done(
                    finish_reason=getattr(event, "finish_reason", None),
                    content_buf=content_buf,
                    ctx=ctx,
                )
                return

            if event_type == "error":
                error_chunk = StreamingChunk(
                    type="error",
                    seq=ctx.next_seq(),
                    error=getattr(event, "error", None),
                )
                yield f"data: {error_chunk.model_dump_json()}\n\n"
                return
        if tool_result_summaries and not terminal_event_seen:
            recovered_text, recovery_failed = await _attempt_runtime_closeout_recovery(
                adapter=adapter,
                messages=messages,
                model=model,
                temperature=temperature,
                working_dir=stream_kwargs.get("working_dir"),
                current_content=content_buf[0],
                tool_result_summaries=tool_result_summaries,
            )
            if not recovery_failed and recovered_text:
                current = content_buf[0]
                if not current:
                    async for chunk in _yield_runtime_text_sse(recovered_text, content_buf=content_buf, ctx=ctx):
                        yield chunk
                elif recovered_text.startswith(current):
                    suffix = recovered_text[len(current):]
                    if suffix:
                        async for chunk in _yield_runtime_text_sse(suffix, content_buf=content_buf, ctx=ctx):
                            yield chunk
                elif recovered_text != current:
                    async for chunk in _yield_runtime_text_sse(
                        f"\n\n{recovered_text}",
                        content_buf=content_buf,
                        ctx=ctx,
                    ):
                        yield chunk
                yield await _emit_runtime_done(
                    finish_reason="end_turn",
                    content_buf=content_buf,
                    ctx=ctx,
                )
                return
            async for chunk in _yield_runtime_fallback_done(finish_reason="end_turn"):
                yield chunk
            return
    finally:
        await runtime_session.close()


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
        async for chunk in _iter_runtime_session_sse_with_tools(
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
