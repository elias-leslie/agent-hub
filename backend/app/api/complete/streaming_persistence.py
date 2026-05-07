"""Persistence helpers for streaming completion — DB saves, audit logging, session cleanup."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.events import publish_message, publish_tool_result, publish_tool_use
from app.services.session_live_activity import mark_session_completed

from .event_helpers import save_events
from .schemas import MessageInput, StreamingChunk
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
                source_metadata=source_metadata,
            )
            logger.info("Streaming: saved messages for session %s", session_id)
    except Exception as save_err:
        logger.error("Failed to save streaming messages: %s", save_err)


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
    """Track inline tags (feedback, summaries, citations) in streaming content."""
    if not accumulated_content:
        return
    # Process inline feedback + summary tags through the shared non-streaming path.
    try:
        from app.db import async_session

        from .citation_tracker import _track_inline_tags

        async with async_session() as db:
            await _track_inline_tags(accumulated_content, db, session_id, agent_id, model_used)
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
        source_metadata=ctx.source_metadata,
    )
    await _track_citations(ctx.session_id, accumulated_content, ctx.agent_used, ctx.model_used)
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
    if ctx.routing_decision_id:
        from app.db import async_session
        from app.services.adaptive_model_router import mark_routing_decision_completed

        async with async_session() as db:
            await mark_routing_decision_completed(
                db,
                ctx.routing_decision_id,
                status="completed",
                latency_ms=int((time.monotonic() - ctx.stream_start) * 1000),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

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
        routing_mode=ctx.routing_mode,
        workload_profile=ctx.workload_profile,
        routing_decision_id=ctx.routing_decision_id,
        auto_candidate_model_id=ctx.auto_candidate_model_id,
        routing_canary_percent=ctx.routing_canary_percent,
        cost_usd=cost_usd,
        thinking_tokens=getattr(event, "thinking_tokens", None),
    )
    return f"data: {done_chunk.model_dump_json()}\n\n"
