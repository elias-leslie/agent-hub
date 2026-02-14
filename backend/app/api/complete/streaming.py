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
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    Yields:
        SSE formatted strings: "data: {json}\n\n"
    """
    adapter = get_adapter(provider)

    input_tokens = 0
    output_tokens = 0
    accumulated_content = ""
    stream_start = time.monotonic()

    # Send connected event immediately with session_id so frontend can update URL
    connected_chunk = StreamingChunk(type="connected", session_id=session_id)
    yield f"data: {connected_chunk.model_dump_json()}\n\n"

    try:
        async for event in adapter.stream(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if event.type == "content":
                accumulated_content += event.content or ""
                chunk = StreamingChunk(type="content", content=event.content)
                yield f"data: {chunk.model_dump_json()}\n\n"

            elif event.type == "done":
                # Capture final token counts
                if event.input_tokens is not None:
                    input_tokens = event.input_tokens
                if event.output_tokens is not None:
                    output_tokens = event.output_tokens

                # Save messages to database using a fresh session
                # (The request-scoped db session may be closed by now)
                if user_messages and accumulated_content:
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

                # Close one-shot streaming sessions (no continuation expected)
                if is_new_session and is_one_shot:
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

                # Send final done event with all metadata
                done_chunk = StreamingChunk(
                    type="done",
                    model=model,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=event.finish_reason,
                    session_id=session_id,
                    agent_used=agent_used,
                    model_used=model_used,
                    fallback_used=fallback_used if agent_used else None,
                )
                yield f"data: {done_chunk.model_dump_json()}\n\n"

            elif event.type == "error":
                error_chunk = StreamingChunk(type="error", error=event.error)
                yield f"data: {error_chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_chunk = StreamingChunk(type="error", error=str(e))
        yield f"data: {error_chunk.model_dump_json()}\n\n"

    # Send [DONE] signal (OpenAI compat)
    yield "data: [DONE]\n\n"
