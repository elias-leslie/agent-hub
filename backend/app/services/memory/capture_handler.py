from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .episode_creator_models import CreateResult

from .enrichment import enrich_memory_content
from .episode_creator import get_episode_creator
from .ingestion_config import CHAT_STREAM, LEARNING, TOOL_DISCOVERY, TOOL_GOTCHA, IngestionConfig
from .observation_schema import ObservationRequest, ObservationResponse, ObservationType
from .privacy_filter import apply_privacy_filter
from .service import MemoryScope

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

_OBS_TYPE_TO_EVENT_TYPE: dict[str, str] = {
    "tool_use": "tool_use",
    "decision": "assistant_message",
    "change": "tool_result",
    "learning": "assistant_message",
    "error": "error",
    "pattern": "assistant_message",
    "context_switch": "system_message",
    "decision_made": "assistant_message",
    "workflow_observed": "tool_use",
}


async def _get_next_seq_and_turn(db: AsyncSession, session_id: str) -> tuple[int, int]:
    """Return (next_sequence, current_turn) for the given session."""
    from sqlalchemy import func, select

    from app.models import SessionEvent

    max_result = await db.execute(
        select(func.coalesce(func.max(SessionEvent.sequence), 0)).where(
            SessionEvent.session_id == session_id
        )
    )
    next_seq = (max_result.scalar() or 0) + 1

    max_turn_result = await db.execute(
        select(func.coalesce(func.max(SessionEvent.turn), 0)).where(
            SessionEvent.session_id == session_id
        )
    )
    current_turn = max(max_turn_result.scalar() or 0, 1)
    return next_seq, current_turn


async def _store_as_session_event(
    request: ObservationRequest,
    filtered_content: str,
    filtered_narrative: str | None,
) -> None:
    """Store observation as a PostgreSQL session_event for transcript/summary support."""
    if not request.session_id:
        return

    try:
        from sqlalchemy import select

        from app.db import _get_session_factory
        from app.models import Session, SessionEvent

        session_factory = _get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Session.id).where(Session.id == request.session_id)
            )
            if not result.scalar_one_or_none():
                logger.debug("Session %s not in DB, skipping event store", request.session_id)
                return

            next_seq, current_turn = await _get_next_seq_and_turn(db, request.session_id)
            event_type = _OBS_TYPE_TO_EVENT_TYPE.get(request.type.value, "tool_use")
            tool_name = request.title[6:] if request.title.startswith("Tool: ") else None

            event = SessionEvent(
                session_id=request.session_id,
                turn=current_turn,
                sequence=next_seq,
                event_type=event_type,
                content=filtered_narrative or filtered_content[:2000],
                tool_name=tool_name or request.title,
                tool_input={"content": filtered_content[:1000]} if filtered_content else None,
                model_used=request.model,
            )
            db.add(event)
            await db.commit()
            logger.debug("Stored session_event for session %s (seq=%d)", request.session_id, next_seq)
    except Exception as e:
        logger.warning("Failed to store session_event: %s", e)

_TYPE_TO_CONFIG: dict[ObservationType, IngestionConfig] = {
    ObservationType.TOOL_USE: TOOL_DISCOVERY,
    ObservationType.LEARNING: LEARNING,
    ObservationType.ERROR: TOOL_GOTCHA,
    ObservationType.DECISION: CHAT_STREAM,
    ObservationType.CHANGE: CHAT_STREAM,
    ObservationType.PATTERN: TOOL_DISCOVERY,
}


def _build_observation_source_description(request: ObservationRequest) -> str:
    parts = [
        f"observation:{request.source.value}",
        f"type:{request.type.value}",
    ]
    if request.session_id:
        parts.append(f"session:{request.session_id}")
    if request.task_id:
        parts.append(f"task:{request.task_id}")
    if request.provider:
        parts.append(f"provider:{request.provider}")
    if request.model:
        parts.append(f"model:{request.model}")
    if request.files_modified:
        parts.append(f"files_modified:{','.join(request.files_modified[:5])}")
    if request.files_read:
        parts.append(f"files_read:{','.join(request.files_read[:5])}")
    if request.concepts:
        parts.append(f"concepts:{','.join(request.concepts[:5])}")
    return " ".join(parts)


def _build_episode_body(
    request: ObservationRequest,
    filtered_content: str,
    filtered_narrative: str | None,
) -> str:
    """Assemble the episode body text from title, content, and optional narrative."""
    body_parts = [f"[{request.title}]", filtered_content]
    if filtered_narrative:
        body_parts.append(f"Context: {filtered_narrative}")
    return "\n".join(body_parts)


def _schedule_background_task(coro: object) -> None:
    """Add a coroutine as a tracked background asyncio task."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _fire_sse_broadcast(
    request: ObservationRequest,
    result: CreateResult,
    now: datetime,
    filtered_content: str,
) -> None:
    """Broadcast a CaptureEvent to the SSE capture stream (fire-and-forget)."""
    try:
        from .capture_stream import CaptureEvent, get_capture_stream

        stream = get_capture_stream()
        capture_event = CaptureEvent(
            event_type="observation",
            timestamp=now.isoformat(),
            data={
                "uuid": result.uuid or "",
                "title": request.title,
                "content": filtered_content[:200],
                "source": request.source.value,
                "type": request.type.value,
                "session_id": request.session_id,
                "stored": True,
            },
        )
        _schedule_background_task(stream.broadcast(capture_event))
    except Exception:
        logger.debug("SSE broadcast failed for observation capture", exc_info=True)


def _apply_privacy_filters(
    request: ObservationRequest,
) -> tuple[str, str | None, dict[str, int]]:
    """Apply privacy filters to content and narrative; return filtered values and stats."""
    filtered_content, content_stats = apply_privacy_filter(request.content)
    filtered_narrative: str | None = None
    if request.narrative:
        filtered_narrative, _ = apply_privacy_filter(request.narrative)
    return filtered_content, filtered_narrative, content_stats


async def capture_observation(
    request: ObservationRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> ObservationResponse:
    filtered_content, filtered_narrative, content_stats = _apply_privacy_filters(request)

    if content_stats["private_tags_stripped"] > 0:
        logger.info(
            "Privacy filter stripped %d private tag(s) from observation",
            content_stats["private_tags_stripped"],
        )

    now = datetime.now(UTC)
    episode_name = f"{request.source.value}_{request.type.value}_{now.isoformat()}"
    creator = get_episode_creator(scope, scope_id)
    episode_body = _build_episode_body(request, filtered_content, filtered_narrative)
    enrichment = enrich_memory_content(
        episode_body,
        source=request.source.value,
        observation_type=request.type.value,
    )
    metadata = dict(enrichment.metadata)
    metadata["capture"] = {
        "source": request.source.value,
        "observation_type": request.type.value,
        "session_id": request.session_id,
        "task_id": request.task_id,
        "provider": request.provider,
        "model": request.model,
        "files_modified": request.files_modified[:20],
        "files_read": request.files_read[:20],
        "concepts": request.concepts[:20],
    }
    result = await creator.create(
        content=episode_body,
        name=episode_name,
        config=_TYPE_TO_CONFIG.get(request.type, LEARNING),
        source_description=_build_observation_source_description(request),
        reference_time=now,
        summary=enrichment.summary,
        metadata=metadata,
        sensitivity_tier=enrichment.sensitivity_tier,
    )

    if result.success:
        # Dual-store: also save as session_event in PostgreSQL for summaries
        if request.session_id:
            _schedule_background_task(
                _store_as_session_event(request, filtered_content, filtered_narrative)
            )
        # Broadcast to SSE capture stream (fire-and-forget)
        _fire_sse_broadcast(request, result, now, filtered_content)

        return ObservationResponse(
            uuid=result.uuid or "",
            stored=True,
            message="Observation captured successfully",
            episode_name=episode_name,
        )

    return ObservationResponse(
        uuid="",
        stored=False,
        message=f"Failed to capture observation: {result.validation_error or 'unknown error'}",
        episode_name=episode_name,
    )
