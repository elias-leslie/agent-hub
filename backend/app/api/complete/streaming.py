"""Streaming completion logic for completion API."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.adapters.registry import get_adapter
from app.adapters.thinking import get_thinking_config

from .schemas import MessageInput, StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import build_done_sse
from .streaming_tool_loop import (
    DEFAULT_MAX_TOOL_TURNS,
    iter_stream_sse_with_tools,
    sse_for_simple_event,
)
from .turn_budget import resolve_tool_max_turns

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds — keeps SSE connections alive through proxies
_HEARTBEAT_INTERVAL_S = 15

# Re-export private alias used historically as _StreamContext
_StreamContext = StreamContext


async def _iter_stream_sse(
    adapter: object,
    messages: object,
    model: str,
    max_tokens: object,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
) -> AsyncIterator[str]:
    """Yield SSE strings from adapter stream events (no tool execution)."""
    async for event in adapter.stream(  # type: ignore[attr-defined]
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        **stream_kwargs,
    ):
        if getattr(event, "type", None) == "done":
            yield await build_done_sse(
                event=event, ctx=ctx,
                accumulated_content=content_buf[0], seq=ctx.next_seq(),
            )
            continue
        sse = sse_for_simple_event(event, content_buf, ctx)
        if sse is not None:
            yield sse


async def _with_heartbeat(
    inner: AsyncIterator[str],
    interval: float = _HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Wrap an SSE iterator with periodic heartbeat comments.

    Emits ``: heartbeat\\n\\n`` when no data flows for ``interval`` seconds,
    keeping the connection alive through reverse proxies and load balancers.

    Iterates the inner generator directly (same task) to avoid corrupting
    anyio cancel scopes — the Claude SDK uses anyio task groups internally,
    and wrapping ``__anext__`` in a separate task (via ``asyncio.ensure_future``
    or a drain task) breaks anyio's task-local cancel scope tracking, leaving
    ``CancelScope._deliver_cancellation`` spinning at 100% CPU.
    """
    last_yield = time.monotonic()
    async for chunk in inner:
        now = time.monotonic()
        while now - last_yield >= interval:
            yield ": heartbeat\n\n"
            last_yield += interval
        yield chunk
        last_yield = time.monotonic()


def _choose_inner_stream(
    adapter: object,
    messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
    tools: list[dict[str, object]] | None,
    project_id: str | None,
    max_tool_turns: int,
) -> AsyncIterator[str]:
    """Select tool-loop or simple stream iterator based on whether tools are present."""
    if tools:
        return iter_stream_sse_with_tools(
            adapter, messages, model, max_tokens, temperature,
            stream_kwargs, content_buf, ctx, project_id, max_tool_turns,
        )
    return _iter_stream_sse(
        adapter, messages, model, max_tokens, temperature,
        stream_kwargs, content_buf, ctx,
    )


async def stream_completion(
    messages: list[Message],
    model: str,
    provider: str,
    temperature: float,
    session_id: str,
    thinking_level: str | None = None,
    agent_used: str | None = None,
    model_used: str | None = None,
    fallback_used: bool = False,
    max_tokens: int | None = None,
    db: AsyncSession | None = None,
    user_messages: list[MessageInput] | None = None,
    is_new_session: bool = False,
    is_one_shot: bool = False,
    tools: list[dict[str, object]] | None = None,
    project_id: str | None = None,
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
    working_dir: str | None = None,
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    Yields SSE formatted strings: "data: {json}\\n\\n". Includes automatic
    heartbeat every 15s to keep connections alive through reverse proxies.
    When tools are provided, runs a multi-turn tool execution loop.
    """
    adapter = get_adapter(provider)
    content_buf: list[str] = [""]
    stream_kwargs: dict[str, object] = {"tools": tools} if tools else {}
    if session_id:
        stream_kwargs["prompt_cache_key"] = session_id
    if thinking_level:
        thinking_config = get_thinking_config(model, thinking_level, provider)
        if thinking_config:
            stream_kwargs.update(thinking_config)
        elif provider not in {"codex", "openai", "openrouter", "zhipu", "minimax", "xai"}:
            stream_kwargs["thinking_level"] = thinking_level
    ctx = StreamContext.open(
        session_id=session_id,
        model=model,
        provider=provider,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used,
        user_messages=user_messages,
        stream_start=time.monotonic(),
        is_new_session=is_new_session,
        is_one_shot=is_one_shot,
        project_id=project_id,
    )
    stream_kwargs["abort_event"] = ctx.cancel_event
    if working_dir:
        stream_kwargs["working_dir"] = working_dir
    yield f"data: {StreamingChunk(type='connected', seq=ctx.next_seq(), session_id=session_id).model_dump_json()}\n\n"
    try:
        effective_tool_turns = resolve_tool_max_turns(provider, max_tool_turns) if tools else max_tool_turns
        inner = _choose_inner_stream(
            adapter, messages, model, max_tokens, temperature,
            stream_kwargs, content_buf, ctx, tools, project_id, effective_tool_turns,
        )
        async for sse in _with_heartbeat(inner):
            yield sse
    except Exception as exc:
        logger.error("Streaming error: %s", exc)
        yield f"data: {StreamingChunk(type='error', seq=ctx.next_seq(), error=str(exc)).model_dump_json()}\n\n"
    finally:
        ctx.close()
        yield "data: [DONE]\n\n"
