"""Streaming completion logic for completion API."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as DBSession

from .event_helpers import save_events
from .helpers import get_adapter
from .schemas import MessageInput, StreamingChunk

if TYPE_CHECKING:
    from app.adapters.base import Message

logger = logging.getLogger(__name__)


async def _save_messages_to_db(
    session_id: str,
    user_messages: list[MessageInput],
    accumulated_content: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    agent_used: str | None,
    stream_start: float,
) -> None:
    """Save streamed messages to the database using a fresh session."""
    if not user_messages or not accumulated_content:
        return
    try:
        from app.db import async_session

        stream_duration_ms = int((time.monotonic() - stream_start) * 1000)
        async with async_session() as fresh_db:
            await save_events(
                db=fresh_db,
                session_id=session_id,
                user_messages=user_messages,
                assistant_content=accumulated_content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model_used=model,
                agent_id=agent_used,
                duration_ms=stream_duration_ms,
            )
            logger.info(f"Streaming: saved messages for session {session_id}")
    except Exception as save_err:
        logger.error(f"Failed to save streaming messages: {save_err}")


async def _close_one_shot_session(session_id: str) -> None:
    """Mark a one-shot session as completed in the database."""
    try:
        from sqlalchemy import select

        from app.db import async_session

        async with async_session() as fresh_db:
            result = await fresh_db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.status = "completed"
                await fresh_db.commit()
                logger.info(f"Streaming: closed one-shot session {session_id}")
    except Exception as close_err:
        logger.error(f"Failed to close one-shot session: {close_err}")


async def _build_done_sse(
    event: object,
    session_id: str,
    model: str,
    provider: str,
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    user_messages: list[MessageInput] | None,
    accumulated_content: str,
    stream_start: float,
    is_new_session: bool,
    is_one_shot: bool,
) -> str:
    """Persist completion data and return the SSE done chunk string."""
    input_tokens = event.input_tokens if event.input_tokens is not None else 0  # type: ignore[attr-defined]
    output_tokens = event.output_tokens if event.output_tokens is not None else 0  # type: ignore[attr-defined]
    await _save_messages_to_db(
        session_id=session_id,
        user_messages=user_messages or [],
        accumulated_content=accumulated_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        agent_used=agent_used,
        stream_start=stream_start,
    )
    if is_new_session and is_one_shot:
        await _close_one_shot_session(session_id)
    # Calculate cost from token counts
    from app.services.token_counter import estimate_cost

    cost = estimate_cost(input_tokens, output_tokens, model)

    thinking_tokens = getattr(event, "thinking_tokens", None)

    done_chunk = StreamingChunk(
        type="done",
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=event.finish_reason,  # type: ignore[attr-defined]
        session_id=session_id,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used if agent_used else None,
        cost_usd=cost.total_cost_usd,
        thinking_tokens=thinking_tokens,
    )
    return f"data: {done_chunk.model_dump_json()}\n\n"


def _sse_for_simple_event(event: object, content_buf: list[str]) -> str | None:
    """Return SSE string for content/tool_use/error events; None for unknown types."""
    event_type = event.type  # type: ignore[attr-defined]
    if event_type == "content":
        content_buf[0] += event.content or ""  # type: ignore[attr-defined]
        chunk = StreamingChunk(type="content", content=event.content)  # type: ignore[attr-defined]
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_use":
        chunk = StreamingChunk(
            type="tool_use",
            tool_id=event.tool_id,  # type: ignore[attr-defined]
            tool_name=event.tool_name,  # type: ignore[attr-defined]
            tool_input=event.tool_input,  # type: ignore[attr-defined]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "error":
        error_chunk = StreamingChunk(type="error", error=event.error)  # type: ignore[attr-defined]
        return f"data: {error_chunk.model_dump_json()}\n\n"
    return None


class _StreamContext:
    """Holds context needed while iterating stream events."""

    __slots__ = (
        "agent_used", "fallback_used", "is_new_session", "is_one_shot",
        "model", "model_used", "provider", "session_id", "stream_start",
        "user_messages",
    )

    def __init__(
        self,
        session_id: str,
        model: str,
        provider: str,
        agent_used: str | None,
        model_used: str | None,
        fallback_used: bool,
        user_messages: list[MessageInput] | None,
        stream_start: float,
        is_new_session: bool,
        is_one_shot: bool,
    ) -> None:
        self.session_id = session_id
        self.model = model
        self.provider = provider
        self.agent_used = agent_used
        self.model_used = model_used
        self.fallback_used = fallback_used
        self.user_messages = user_messages
        self.stream_start = stream_start
        self.is_new_session = is_new_session
        self.is_one_shot = is_one_shot


async def _iter_stream_sse(adapter: object, messages: object, model: str, max_tokens: object, temperature: float, stream_kwargs: dict[str, object], content_buf: list[str], ctx: _StreamContext) -> AsyncIterator[str]:
    """Yield SSE strings from adapter stream events."""
    async for event in adapter.stream(messages=messages, model=model, max_tokens=max_tokens, temperature=temperature, **stream_kwargs):  # type: ignore[attr-defined]
        if event.type == "done":
            yield await _build_done_sse(event=event, session_id=ctx.session_id, model=ctx.model, provider=ctx.provider, agent_used=ctx.agent_used, model_used=ctx.model_used, fallback_used=ctx.fallback_used, user_messages=ctx.user_messages, accumulated_content=content_buf[0], stream_start=ctx.stream_start, is_new_session=ctx.is_new_session, is_one_shot=ctx.is_one_shot)
            continue
        sse = _sse_for_simple_event(event, content_buf)
        if sse is not None:
            yield sse


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
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    Yields:
        SSE formatted strings: "data: {json}\n\n"
    """
    adapter = get_adapter(provider)
    content_buf: list[str] = [""]
    stream_kwargs: dict[str, object] = {"tools": tools} if tools else {}
    ctx = _StreamContext(
        session_id=session_id, model=model, provider=provider,
        agent_used=agent_used, model_used=model_used, fallback_used=fallback_used,
        user_messages=user_messages, stream_start=time.monotonic(),
        is_new_session=is_new_session, is_one_shot=is_one_shot,
    )
    yield f"data: {StreamingChunk(type='connected', session_id=session_id).model_dump_json()}\n\n"
    try:
        async for sse in _iter_stream_sse(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx):
            yield sse
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        yield f"data: {StreamingChunk(type='error', error=str(e)).model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
