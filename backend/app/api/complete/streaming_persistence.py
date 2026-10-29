"""Persistence helpers for streaming completion — DB saves, audit logging, session cleanup."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import update

from app.llm.types import AssistantMessage
from app.models import Session as DBSession
from app.models import SessionEvent, SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.events import publish_message, publish_tool_result, publish_tool_use
from app.services.session_live_activity import mark_session_completed

from .event_helpers import TurnTraceStep, save_events, save_user_message_events
from .schemas import MessageInput
from .streaming_context import StreamContext

logger = logging.getLogger(__name__)

_STREAM_PROGRESS_MIN_CHARS = 120
_STREAM_PROGRESS_MIN_INTERVAL_S = 3.0


async def save_messages_to_db(
    session_id: str,
    user_messages: list[MessageInput],
    accumulated_content: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    agent_used: str | None,
    stream_start: float,
    source_metadata: dict[str, object] | None = None,
    usage: dict[str, object] | None = None,
    trace: Sequence[TurnTraceStep] = (),
    thinking_tokens: int | None = None,
    prompt_event_id: str | None = None,
) -> None:
    """Save streamed messages to the database using a fresh session.

    ``prompt_event_id`` names a prompt already stored at turn start; it gets this turn's input tokens.
    """
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
                source_metadata=source_metadata,
                usage=usage,
                trace=trace,
                thinking_tokens=thinking_tokens,
                commit=prompt_event_id is None,
            )
            if prompt_event_id is not None:
                await fresh_db.execute(
                    update(SessionEvent).where(SessionEvent.id == prompt_event_id).values(tokens=input_tokens)
                )
                await fresh_db.commit()
            logger.info("Streaming: saved messages for session %s", session_id)
    except Exception as save_err:
        logger.error("Failed to save streaming messages: %s", save_err)


async def save_turn_prompt_to_db(
    session_id: str,
    user_messages: list[MessageInput],
    source_metadata: dict[str, object] | None = None,
    agent_used: str | None = None,
) -> str | None:
    """Store the prompt that starts a turn, so every client that opens the session mid-turn sees it.

    Returns the stored event's id; the end-of-turn save then must not store it again, only add its tokens.
    """
    if not any(msg.role in ("user", "system") for msg in user_messages):
        return None
    try:
        from app.db import async_session

        async with async_session() as fresh_db:
            event = await save_user_message_events(fresh_db, session_id, user_messages, None, agent_used, source_metadata)
            await fresh_db.commit()
        return str(event.id) if event is not None else None
    except Exception as save_err:
        logger.error("Failed to save the turn's prompt: %s", save_err)
        return None


async def _with_fresh_session(
    session_id: str,
    callback,
) -> None:
    """Load a fresh session row, run callback(session, db), and commit if present."""
    try:
        from app.db import async_session

        async with async_session() as fresh_db:
            session = await fresh_db.get(DBSession, session_id)
            if session is None:
                return
            await callback(session, fresh_db)
            await fresh_db.commit()
    except Exception as exc:
        logger.warning("Streaming live update failed for %s: %s", session_id, exc)


def should_publish_stream_progress(ctx: StreamContext, content: str) -> bool:
    """Throttle live assistant-progress updates during streaming."""
    stripped = content.strip()
    if not stripped:
        return False

    content_len = len(stripped)
    now = time.monotonic()
    if content_len < ctx.last_progress_chars:
        ctx.reset_progress_cursor()

    should_publish = (
        ctx.last_progress_chars == 0
        or content_len - ctx.last_progress_chars >= _STREAM_PROGRESS_MIN_CHARS
        or now - ctx.last_progress_at >= _STREAM_PROGRESS_MIN_INTERVAL_S
    )
    if not should_publish:
        return False

    ctx.last_progress_chars = content_len
    ctx.last_progress_at = now
    return True


async def publish_stream_progress(ctx: StreamContext, content: str) -> None:
    """Mirror partial assistant progress into live session truth + WS subscribers."""
    stripped = content.strip()
    if not stripped:
        return

    await publish_message(ctx.session_id, "assistant", stripped)

    async def _update(session: DBSession, _db) -> None:
        from app.services.session_live_activity import update_live_activity_for_event

        update_live_activity_for_event(
            session,
            event_type="assistant_message",
            content=stripped,
            model_used=ctx.model_used or ctx.model,
        )

    await _with_fresh_session(ctx.session_id, _update)


async def mirror_stream_tool_use(
    ctx: StreamContext,
    tool_name: str,
    tool_input: dict[str, object],
) -> None:
    """Publish and persist a live tool-use breadcrumb for streaming sessions."""
    await publish_tool_use(ctx.session_id, tool_name, tool_input)

    async def _update(_session: DBSession, db) -> None:
        from app.services.event_storage import store_tool_use_event

        await store_tool_use_event(
            db,
            ctx.session_id,
            tool_name,
            tool_input,
            model_used=ctx.model_used or ctx.model,
            agent_id=ctx.agent_used,
            **(ctx.source_metadata or {}),
        )

    await _with_fresh_session(ctx.session_id, _update)


async def mirror_stream_tool_result(
    ctx: StreamContext,
    tool_name: str,
    result_content: str,
    *,
    duration_ms: int | None,
    is_error: bool,
) -> None:
    """Publish and persist a live tool-result breadcrumb for streaming sessions."""
    tool_output = {"content": result_content, "is_error": is_error}
    await publish_tool_result(
        ctx.session_id,
        tool_name,
        tool_output,
        duration_ms=duration_ms,
        is_error=is_error,
    )

    async def _update(_session: DBSession, db) -> None:
        from app.services.event_storage import store_tool_result_event

        await store_tool_result_event(
            db,
            ctx.session_id,
            tool_name,
            tool_output,
            duration_ms=duration_ms,
            model_used=ctx.model_used or ctx.model,
            agent_id=ctx.agent_used,
            **(ctx.source_metadata or {}),
        )

    await _with_fresh_session(ctx.session_id, _update)


async def mirror_stream_outcome_error(ctx: StreamContext, message: AssistantMessage, usage: dict[str, object]) -> None:
    """Persist a failed streaming attempt that carries a typed provider outcome (refusal, switch, limit)."""

    async def _update(_session: DBSession, db) -> None:
        from app.services.event_storage import store_error_event

        await store_error_event(
            db,
            ctx.session_id,
            "provider_outcome",
            message.error_message or "Provider stream failed",
            agent_id=ctx.agent_used,
            model_used=message.model,
            usage=usage,
        )

    await _with_fresh_session(ctx.session_id, _update)


async def mirror_stream_request_metrics(ctx: StreamContext, message: AssistantMessage) -> None:
    """Persist a finished model request's liveness record and its retries."""
    from .request_metrics import model_request_record, store_model_requests

    if model_request_record(message) is None:
        return

    async def _update(_session: DBSession, db) -> None:
        await store_model_requests(
            db, ctx.session_id, [message], model_used=ctx.model_used or ctx.model, agent_id=ctx.agent_used,
        )

    await _with_fresh_session(ctx.session_id, _update)


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
                    termination_reason=None,
                )
                session.last_activity_at = datetime.now(UTC)
                await store_child_session_lifecycle_event(
                    fresh_db,
                    session,
                    SessionEventType.CHILD_SESSION_RESULT,
                    summary="Child session completed",
                    status="completed",
                )
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


async def _track_citations(
    session_id: str,
    accumulated_content: str,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> None:
    """Track inline tags (summaries, citations) in streaming content."""
    if not accumulated_content:
        return
    # Process inline summary tags through the shared non-streaming path.
    try:
        from app.db import async_session

        from .citation_tracker import _track_inline_tags

        async with async_session() as db:
            await _track_inline_tags(accumulated_content, db, session_id, agent_id)
            await db.commit()
    except Exception as exc:
        logger.warning("Streaming inline tag tracking failed: %s", exc)

    # Process citations separately
    try:
        from app.services.memory.citation_parser import extract_uuid_prefixes

        prefixes = extract_uuid_prefixes(accumulated_content)
        if prefixes:
            from app.services.memory.session_analysis import analyze_session

            await analyze_session(session_id, citation_prefixes=prefixes)

            # Also persist memory_cite session events (parity with non-streaming path)
            from app.db import async_session

            from ._citation_helpers import _resolve_cited_uuids, _store_cite_event

            cited_uuids = await _resolve_cited_uuids(accumulated_content, None)
            if cited_uuids:
                async with async_session() as db:
                    await _store_cite_event(db, session_id, cited_uuids, agent_id, model_used)
                    await db.commit()
    except Exception as exc:
        logger.warning("Streaming citation tracking failed: %s", exc)
