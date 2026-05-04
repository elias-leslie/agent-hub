"""Runtime-session streaming tool loop helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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
    should_publish_stream_progress,
)
from .tool_event_processor import _summarize_tool_result

logger = logging.getLogger(__name__)


@dataclass
class _RuntimeToolState:
    content_buf: list[str]
    ctx: StreamContext
    tool_names_by_id: dict[str, str] = field(default_factory=dict)
    tool_result_summaries: list[str] = field(default_factory=list)
    terminal_event_seen: bool = False


def _facade() -> Any:
    from . import streaming_tool_loop

    return streaming_tool_loop


async def _yield_runtime_text_sse(
    text: str,
    *,
    state: _RuntimeToolState,
) -> AsyncIterator[str]:
    if not text:
        return
    state.content_buf[0] += text
    yield f"data: {StreamingChunk(type='content', seq=state.ctx.next_seq(), content=text).model_dump_json()}\n\n"
    if should_publish_stream_progress(state.ctx, state.content_buf[0]):
        await _facade().publish_stream_progress(state.ctx, state.content_buf[0])


async def _emit_runtime_done(
    *,
    finish_reason: str | None,
    state: _RuntimeToolState,
) -> str:
    return await _facade().build_done_sse(
        event=SimpleNamespace(
            input_tokens=0,
            output_tokens=0,
            finish_reason=finish_reason,
        ),
        ctx=state.ctx,
        accumulated_content=state.content_buf[0],
        seq=state.ctx.next_seq(),
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


async def _runtime_fallback_done(
    state: _RuntimeToolState,
    *,
    finish_reason: str | None,
) -> AsyncIterator[str]:
    if not state.tool_result_summaries:
        return
    fallback_content = build_tool_closeout_fallback(
        state.content_buf[0],
        state.tool_result_summaries,
    )
    if fallback_content != state.content_buf[0]:
        state.content_buf[0] = fallback_content
        yield f"data: {StreamingChunk(type='content', seq=state.ctx.next_seq(), content=fallback_content).model_dump_json()}\n\n"
        await _facade().publish_stream_progress(state.ctx, state.content_buf[0])
    yield await _emit_runtime_done(finish_reason=finish_reason, state=state)


async def _yield_text_delta(
    final_text: str,
    *,
    state: _RuntimeToolState,
    prefix_when_different: bool,
) -> AsyncIterator[str]:
    if not final_text:
        return
    current = state.content_buf[0]
    if not current:
        async for chunk in _yield_runtime_text_sse(final_text, state=state):
            yield chunk
    elif final_text.startswith(current):
        suffix = final_text[len(current):]
        if suffix:
            async for chunk in _yield_runtime_text_sse(suffix, state=state):
                yield chunk
    elif prefix_when_different and final_text != current:
        async for chunk in _yield_runtime_text_sse(f"\n\n{final_text}", state=state):
            yield chunk


async def _handle_assistant_event(event: object, state: _RuntimeToolState) -> AsyncIterator[str]:
    blocks = getattr(getattr(event, "message", None), "content", []) or []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            async for chunk in _yield_runtime_text_sse(getattr(block, "text", "") or "", state=state):
                yield chunk
        elif block_type == "thinking":
            thinking_text = getattr(block, "text", "") or ""
            if thinking_text:
                yield f"data: {StreamingChunk(type='thinking', seq=state.ctx.next_seq(), content=thinking_text).model_dump_json()}\n\n"
        elif block_type == "tool_use":
            async for chunk in _handle_tool_use_block(block, state):
                yield chunk


async def _handle_tool_use_block(block: object, state: _RuntimeToolState) -> AsyncIterator[str]:
    tool_id = getattr(block, "id", "") or ""
    tool_name = getattr(block, "name", "") or "unknown"
    tool_input = getattr(block, "input", None) or {}
    if tool_id:
        state.tool_names_by_id[tool_id] = tool_name
    await _facade().mirror_stream_tool_use(state.ctx, tool_name, tool_input)
    tool_use_chunk = StreamingChunk(
        type="tool_use",
        seq=state.ctx.next_seq(),
        tool_id=tool_id or None,
        tool_name=tool_name,
        tool_input=tool_input,
    )
    yield f"data: {tool_use_chunk.model_dump_json()}\n\n"


async def _handle_tool_result_event(event: object, state: _RuntimeToolState) -> AsyncIterator[str]:
    tool_content = getattr(event, "content", "") or ""
    tool_id = getattr(event, "tool_use_id", None)
    tool_name = state.tool_names_by_id.get(str(tool_id or ""), str(tool_id or "tool"))
    is_error = bool(getattr(event, "is_error", False))
    summary = _summarize_tool_result(tool_name, tool_content, is_error)
    if summary:
        state.tool_result_summaries.append(summary)
    await _facade().mirror_stream_tool_result(
        state.ctx,
        tool_name,
        tool_content,
        duration_ms=getattr(event, "duration_ms", None),
        is_error=is_error,
    )
    tool_result_chunk = StreamingChunk(
        type="tool_result",
        seq=state.ctx.next_seq(),
        tool_id=tool_id,
        tool_result=tool_content,
        tool_status="error" if is_error else "complete",
    )
    yield f"data: {tool_result_chunk.model_dump_json()}\n\n"


async def _recover_runtime_closeout(
    *,
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    stream_kwargs: dict[str, object],
    state: _RuntimeToolState,
    current_content: str,
) -> tuple[str, bool]:
    recovered_text, recovery_failed = await _attempt_runtime_closeout_recovery(
        adapter=adapter,
        messages=messages,
        model=model,
        temperature=temperature,
        working_dir=stream_kwargs.get("working_dir"),
        current_content=current_content,
        tool_result_summaries=state.tool_result_summaries,
    )
    return recovered_text or current_content, recovery_failed


async def _handle_result_event(
    event: object,
    *,
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    stream_kwargs: dict[str, object],
    state: _RuntimeToolState,
) -> AsyncIterator[str]:
    state.terminal_event_seen = True
    final_text = getattr(event, "result", "") or ""
    async for chunk in _yield_text_delta(final_text, state=state, prefix_when_different=False):
        yield chunk

    closeout_plan = _plan_closeout(final_text or state.content_buf[0], state, allow_recovery=True)
    if closeout_plan.action == "recover":
        final_text, recovery_failed = await _recover_runtime_closeout(
            adapter=adapter,
            messages=messages,
            model=model,
            temperature=temperature,
            stream_kwargs=stream_kwargs,
            state=state,
            current_content=final_text or state.content_buf[0],
        )
        if not recovery_failed:
            async for chunk in _yield_text_delta(final_text, state=state, prefix_when_different=True):
                yield chunk
        closeout_plan = _plan_closeout(final_text, state, allow_recovery=False)

    if closeout_plan.action == "fallback":
        async for chunk in _runtime_fallback_done(state, finish_reason=getattr(event, "finish_reason", None)):
            yield chunk
        return
    yield await _emit_runtime_done(finish_reason=getattr(event, "finish_reason", None), state=state)


def _plan_closeout(text: str, state: _RuntimeToolState, *, allow_recovery: bool) -> Any:
    return plan_user_facing_closeout(
        text,
        tool_calls_count=len(state.tool_result_summaries),
        allow_recovery=allow_recovery,
        recovery_used=not allow_recovery,
        tool_result_summaries=state.tool_result_summaries,
    )


async def _handle_error_event(event: object, state: _RuntimeToolState) -> str:
    error_chunk = StreamingChunk(
        type="error",
        seq=state.ctx.next_seq(),
        error=getattr(event, "error", None),
    )
    return f"data: {error_chunk.model_dump_json()}\n\n"


async def _recover_after_missing_terminal(
    *,
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    stream_kwargs: dict[str, object],
    state: _RuntimeToolState,
) -> AsyncIterator[str]:
    if not state.tool_result_summaries or state.terminal_event_seen:
        return
    recovered_text, recovery_failed = await _recover_runtime_closeout(
        adapter=adapter,
        messages=messages,
        model=model,
        temperature=temperature,
        stream_kwargs=stream_kwargs,
        state=state,
        current_content=state.content_buf[0],
    )
    if not recovery_failed and recovered_text:
        async for chunk in _yield_text_delta(recovered_text, state=state, prefix_when_different=True):
            yield chunk
        yield await _emit_runtime_done(finish_reason="end_turn", state=state)
        return
    async for chunk in _runtime_fallback_done(state, finish_reason="end_turn"):
        yield chunk


async def _handle_runtime_event(
    event: object,
    *,
    adapter: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    stream_kwargs: dict[str, object],
    state: _RuntimeToolState,
) -> tuple[bool, list[str]]:
    event_type = getattr(event, "type", None)
    chunks: list[str] = []
    if event_type == "assistant" and getattr(event, "message", None) is not None:
        async for chunk in _handle_assistant_event(event, state):
            chunks.append(chunk)
    elif event_type == "tool_result":
        async for chunk in _handle_tool_result_event(event, state):
            chunks.append(chunk)
    elif event_type == "result":
        async for chunk in _handle_result_event(
            event,
            adapter=adapter,
            messages=messages,
            model=model,
            temperature=temperature,
            stream_kwargs=stream_kwargs,
            state=state,
        ):
            chunks.append(chunk)
        return True, chunks
    elif event_type == "error":
        chunks.append(await _handle_error_event(event, state))
        return True, chunks
    return False, chunks


async def iter_runtime_session_sse_with_tools(
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
    state = _RuntimeToolState(content_buf=content_buf, ctx=ctx)
    try:
        async for event, _provider_session_id in runtime_session.events():
            done, chunks = await _handle_runtime_event(
                event,
                adapter=adapter,
                messages=messages,
                model=model,
                temperature=temperature,
                stream_kwargs=stream_kwargs,
                state=state,
            )
            for chunk in chunks:
                yield chunk
            if done:
                return
        async for chunk in _recover_after_missing_terminal(
            adapter=adapter,
            messages=messages,
            model=model,
            temperature=temperature,
            stream_kwargs=stream_kwargs,
            state=state,
        ):
            yield chunk
    finally:
        await runtime_session.close()


__all__ = ["iter_runtime_session_sse_with_tools"]
