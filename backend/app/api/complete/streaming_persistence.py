"""Persistence helpers for streaming completion — DB saves, audit logging, session cleanup."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from app.models import Session as DBSession
from app.services.session_live_activity import mark_session_completed

from .event_helpers import save_events
from .schemas import MessageInput, StreamingChunk
from .streaming_context import StreamContext

logger = logging.getLogger(__name__)


async def save_messages_to_db(
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
    if not accumulated_content:
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
            logger.info("Streaming: saved messages for session %s", session_id)
    except Exception as save_err:
        logger.error("Failed to save streaming messages: %s", save_err)


async def close_one_shot_session(session_id: str) -> None:
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
                mark_session_completed(
                    session,
                    summary="Streaming one-shot completed",
                    termination_reason="streaming_one_shot_closed",
                )
                session.last_activity_at = datetime.now(UTC)
                await fresh_db.commit()
                logger.info("Streaming: closed one-shot session %s", session_id)
    except Exception as close_err:
        logger.error("Failed to close one-shot session: %s", close_err)


async def _store_tool_audit(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, object],
    result_content: str,
    is_error: bool,
    duration_ms: int | None,
    sensitivity: str,
    agent_id: str | None,
) -> None:
    """Coroutine that stores a TOOL_AUDIT event in the DB."""
    try:
        from app.db import async_session
        from app.models.session import SessionEventType
        from app.services.event_storage import store_event

        async with async_session() as db:
            await store_event(
                db=db,
                session_id=session_id,
                event_type=SessionEventType.TOOL_AUDIT,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output={
                    "result": result_content[:2000],
                    "is_error": is_error,
                    "sensitivity": sensitivity,
                },
                duration_ms=duration_ms,
                agent_id=agent_id,
            )
            await db.commit()
    except Exception as exc:
        logger.error("Failed to store tool audit event: %s", exc)


def log_tool_audit(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, object],
    result_content: str,
    is_error: bool,
    duration_ms: int | None,
    sensitivity: str,
    agent_id: str | None,
) -> None:
    """Fire-and-forget audit log for sensitive tool executions."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            _store_tool_audit(
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                result_content=result_content,
                is_error=is_error,
                duration_ms=duration_ms,
                sensitivity=sensitivity,
                agent_id=agent_id,
            )
        )
        # Keep a reference to prevent premature garbage collection
        _ = task
    except RuntimeError:
        logger.debug("Could not schedule telemetry task (event loop closed)")


async def _track_citations(session_id: str, accumulated_content: str) -> None:
    """Track inline tags (feedback, summaries, citations) in streaming content."""
    if not accumulated_content:
        return
    # Process inline feedback + summary tags (same code non-streaming path uses)
    summary_stored = False
    try:
        from app.db import async_session

        from .citation_tracker import (
            _ensure_synthetic_summary,
            track_inline_feedback,
            track_inline_summaries,
        )

        async with async_session() as db:
            await track_inline_feedback(accumulated_content, db, session_id)
            summary_stored = await track_inline_summaries(accumulated_content, db, session_id)
            if not summary_stored:
                summary_stored = await _ensure_synthetic_summary(
                    accumulated_content, session_id, db=db
                )
            await db.commit()
    except Exception as exc:
        logger.warning("Streaming inline tag tracking failed: %s", exc)

    # Fallback: generate synthetic summary if no inline [[S:...]] tag was found
    if not summary_stored:
        try:
            await _ensure_synthetic_summary(accumulated_content, session_id)
        except Exception as exc:
            logger.warning("Streaming synthetic summary failed: %s", exc)
    # Process citations separately
    try:
        from app.services.memory.citation_parser import extract_uuid_prefixes

        prefixes = extract_uuid_prefixes(accumulated_content)
        if prefixes:
            from app.services.memory.session_analysis import analyze_session

            await analyze_session(session_id, citation_prefixes=prefixes)
    except Exception as exc:
        logger.warning("Streaming citation tracking failed: %s", exc)


async def _persist_completion(
    ctx: StreamContext,
    accumulated_content: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Save messages, track citations, close one-shot session. Returns total cost USD."""
    await save_messages_to_db(
        session_id=ctx.session_id,
        user_messages=ctx.user_messages or [],
        accumulated_content=accumulated_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=ctx.model,
        agent_used=ctx.agent_used,
        stream_start=ctx.stream_start,
    )
    await _track_citations(ctx.session_id, accumulated_content)
    if ctx.is_new_session and ctx.is_one_shot:
        await close_one_shot_session(ctx.session_id)

    from app.services.token_counter import estimate_cost

    cost = estimate_cost(input_tokens, output_tokens, ctx.model)
    if ctx.project_id and cost.total_cost_usd > 0:
        from app.services.project_budget import record_project_cost

        await record_project_cost(ctx.project_id, cost.total_cost_usd)
    return cost.total_cost_usd


async def build_done_sse(
    event: object,
    ctx: StreamContext,
    accumulated_content: str,
    seq: int,
) -> str:
    """Persist completion data and return the SSE done-chunk string."""
    input_tokens: int = getattr(event, "input_tokens", None) or 0
    output_tokens: int = getattr(event, "output_tokens", None) or 0
    cost_usd = await _persist_completion(ctx, accumulated_content, input_tokens, output_tokens)

    from app.constants.catalog import MODEL_CATALOG_BY_ID

    model_id = ctx.model_used or ctx.model
    catalog_entry = MODEL_CATALOG_BY_ID.get(model_id)
    display_name = catalog_entry.name if catalog_entry else None

    done_chunk = StreamingChunk(
        type="done",
        seq=seq,
        model=ctx.model,
        provider=ctx.provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=getattr(event, "finish_reason", None),
        session_id=ctx.session_id,
        agent_used=ctx.agent_used,
        model_used=ctx.model_used,
        model_display_name=display_name,
        fallback_used=ctx.fallback_used if ctx.agent_used else None,
        cost_usd=cost_usd,
        thinking_tokens=getattr(event, "thinking_tokens", None),
    )
    return f"data: {done_chunk.model_dump_json()}\n\n"
