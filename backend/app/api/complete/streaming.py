"""Streaming completion logic for completion API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message

from .helpers import get_adapter
from .schemas import MessageInput, StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import build_done_sse
from .streaming_tool_loop import (
    DEFAULT_MAX_TOOL_TURNS,
    iter_stream_sse_with_tools,
    sse_for_simple_event,
)

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds — keeps SSE connections alive through proxies
_HEARTBEAT_INTERVAL_S = 15

# Registry of active streaming sessions for cooperative cancellation.
# Maps session_id → asyncio.Event (set when cancellation is requested).
_active_streams: dict[str, asyncio.Event] = {}

# Re-export private alias used historically as _StreamContext
_StreamContext = StreamContext


def register_active_stream(session_id: str) -> asyncio.Event:
    """Register an active stream for cancellation support. Returns the cancel event."""
    event = asyncio.Event()
    _active_streams[session_id] = event
    return event


def cancel_active_stream(session_id: str) -> bool:
    """Signal an active stream to cancel tool execution. Returns True if stream was found."""
    event = _active_streams.get(session_id)
    if event is not None:
        event.set()
        return True
    return False


def _unregister_active_stream(session_id: str) -> None:
    """Remove a stream from the active registry."""
    _active_streams.pop(session_id, None)


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
    async with contextlib.aclosing(
        adapter.stream(  # type: ignore[attr-defined]
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **stream_kwargs,
        )
    ) as stream:
        async for event in stream:
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

    Drains the inner generator in a **single dedicated Task** so that every
    ``__anext__()`` call shares the same asyncio Task — preserving anyio
    cancel-scope affinity required by the Claude SDK.  Items are forwarded
    via an ``asyncio.Queue``; the heartbeat loop reads with a timeout.
    """
    queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

    async def _drain() -> None:
        """Iterate *inner* in one Task and forward items via *queue*."""
        try:
            async with contextlib.aclosing(inner) as stream:
                async for chunk in stream:
                    await queue.put(chunk)
        except BaseException as exc:
            # Forward the exception so the consumer can re-raise it.
            with contextlib.suppress(Exception):
                await queue.put(exc)
        finally:
            with contextlib.suppress(Exception):
                await queue.put(None)  # sentinel: stream ended

    task = asyncio.create_task(_drain())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                if task.done():
                    # Drain finished while we were waiting — grab the sentinel.
                    item = queue.get_nowait() if not queue.empty() else None
                    if item is None:
                        return
                    if isinstance(item, BaseException):
                        raise item
                    yield item
                    continue
                yield ": heartbeat\n\n"
                continue
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _build_stream_context(
    session_id: str,
    model: str,
    provider: str,
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    user_messages: list[MessageInput] | None,
    is_new_session: bool,
    is_one_shot: bool,
    project_id: str | None,
) -> StreamContext:
    """Build a StreamContext with a registered cancel event."""
    cancel_event = register_active_stream(session_id)
    return StreamContext(
        session_id=session_id, model=model, provider=provider,
        agent_used=agent_used, model_used=model_used, fallback_used=fallback_used,
        user_messages=user_messages, stream_start=time.monotonic(),
        is_new_session=is_new_session, is_one_shot=is_one_shot,
        cancel_event=cancel_event, project_id=project_id,
    )


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
    if working_dir:
        stream_kwargs["working_dir"] = working_dir
    ctx = _build_stream_context(
        session_id, model, provider, agent_used, model_used, fallback_used,
        user_messages, is_new_session, is_one_shot, project_id,
    )
    yield f"data: {StreamingChunk(type='connected', seq=ctx.next_seq(), session_id=session_id).model_dump_json()}\n\n"
    try:
        inner = _choose_inner_stream(
            adapter, messages, model, max_tokens, temperature,
            stream_kwargs, content_buf, ctx, tools, project_id, max_tool_turns,
        )
        async for sse in _with_heartbeat(inner):
            yield sse
    except Exception as exc:
        logger.error("Streaming error: %s", exc)
        yield f"data: {StreamingChunk(type='error', seq=ctx.next_seq(), error=str(exc)).model_dump_json()}\n\n"
    finally:
        _unregister_active_stream(session_id)
        yield "data: [DONE]\n\n"
