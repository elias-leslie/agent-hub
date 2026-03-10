"""Unified timeline endpoint for the persona workspace."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.session import Session, SessionEvent

from .constants import HOURS_MAP
from .schemas import PersonaStreamEntry, PersonaStreamEventPreview, PersonaStreamResponse

router = APIRouter()

_CHAT_MESSAGE_TYPES = ("user_message", "assistant_message")
_SEARCHABLE_EVENT_TYPES = (
    "user_message",
    "assistant_message",
    "thinking",
    "tool_use",
    "tool_result",
    "error",
)


def _apply_since(query: Select, hours: int) -> Select:
    if hours <= 0:
        return query
    since = datetime.now(UTC) - timedelta(hours=hours)
    return query.where(Session.created_at >= since)


def _live_activity_summary(session: Session) -> tuple[str | None, str | None]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    live_activity = metadata.get("live_activity")
    if not isinstance(live_activity, dict):
        return None, None
    summary = live_activity.get("summary")
    status = live_activity.get("status")
    return (
        summary if isinstance(summary, str) else None,
        status if isinstance(status, str) else None,
    )


def _session_search_predicates(search: str) -> list[Any]:
    term = f"%{search}%"
    event_match = (
        select(SessionEvent.id)
        .where(
            SessionEvent.session_id == Session.id,
            SessionEvent.event_type.in_(_SEARCHABLE_EVENT_TYPES),
            or_(
                SessionEvent.content.ilike(term),
                SessionEvent.tool_name.ilike(term),
            ),
        )
        .correlate(Session)
        .exists()
    )
    return [
        Session.summary_oneliner.ilike(term),
        Session.project_id.ilike(term),
        Session.agent_slug.ilike(term),
        Session.external_id.ilike(term),
        Session.current_branch.ilike(term),
        event_match,
    ]


def _persona_session_query(hours: int, search: str | None) -> Select:
    has_events = (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )
    query = select(Session).where(Session.agent_slug == "persona", has_events)
    query = _apply_since(query, hours)
    if search:
        query = query.where(or_(*_session_search_predicates(search)))
    return query


def _child_session_query(persona_session_ids: Iterable[str], hours: int, search: str | None) -> Select:
    ids = list(persona_session_ids)
    query = select(Session).where(
        Session.parent_session_id.in_(ids),
        Session.agent_slug.isnot(None),
        Session.agent_slug != "persona",
    )
    query = _apply_since(query, hours)
    if search:
        query = query.where(or_(*_session_search_predicates(search)))
    return query


async def _fetch_message_counts(db: AsyncSession, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}

    query = (
        select(SessionEvent.session_id, func.count().label("cnt"))
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(_CHAT_MESSAGE_TYPES),
        )
        .group_by(SessionEvent.session_id)
    )
    rows = (await db.execute(query)).all()
    return {row.session_id: row.cnt for row in rows}


async def _fetch_tool_counts(db: AsyncSession, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}

    query = (
        select(SessionEvent.session_id, func.count().label("cnt"))
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type == "tool_use",
        )
        .group_by(SessionEvent.session_id)
    )
    rows = (await db.execute(query)).all()
    return {row.session_id: row.cnt for row in rows}


async def _fetch_persona_chat_events(
    db: AsyncSession,
    session_ids: list[str],
    search: str | None,
) -> list[SessionEvent]:
    if not session_ids:
        return []

    query = (
        select(SessionEvent)
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(_CHAT_MESSAGE_TYPES),
        )
        .order_by(SessionEvent.created_at.desc(), SessionEvent.turn.desc(), SessionEvent.sequence.desc())
    )
    if search:
        query = query.where(SessionEvent.content.ilike(f"%{search}%"))
    return list((await db.execute(query)).scalars().all())


async def _fetch_event_previews(
    db: AsyncSession,
    session_ids: list[str],
    *,
    limit_per_session: int = 8,
) -> dict[str, list[PersonaStreamEventPreview]]:
    if not session_ids:
        return {}

    query = (
        select(SessionEvent)
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.notin_(_CHAT_MESSAGE_TYPES),
        )
        .order_by(SessionEvent.created_at.desc(), SessionEvent.turn.desc(), SessionEvent.sequence.desc())
    )
    events = list((await db.execute(query)).scalars().all())
    previews: dict[str, list[PersonaStreamEventPreview]] = {}

    for event in events:
        session_previews = previews.setdefault(event.session_id, [])
        if len(session_previews) >= limit_per_session:
            continue
        preview_content = _stringify_preview(event.content, limit=240)
        session_previews.append(
            PersonaStreamEventPreview(
                id=event.id,
                event_type=event.event_type,
                created_at=event.created_at,
                role=event.role,
                tool_name=event.tool_name,
                content_preview=preview_content,
                tool_input_preview=_stringify_preview(event.tool_input),
                tool_output_preview=_stringify_preview(event.tool_output),
                duration_ms=event.duration_ms,
                model_used=event.model_used,
            )
        )

    return previews


def _stringify_preview(value: Any, *, limit: int = 280) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except TypeError:
            text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _build_stream_entries(
    persona_sessions: list[Session],
    child_sessions: list[Session],
    message_events: list[SessionEvent],
    message_counts: dict[str, int],
    tool_counts: dict[str, int],
    event_previews: dict[str, list[PersonaStreamEventPreview]],
) -> list[PersonaStreamEntry]:
    persona_by_id = {session.id: session for session in persona_sessions}
    entries: list[PersonaStreamEntry] = []

    for event in message_events:
        session = persona_by_id.get(event.session_id)
        if session is None:
            continue
        entries.append(
            PersonaStreamEntry(
                id=event.id,
                entry_type="message",
                timestamp=event.created_at,
                session_id=session.id,
                parent_session_id=session.parent_session_id,
                project_id=session.project_id,
                agent_slug=session.agent_slug,
                session_type=session.session_type,
                status=session.status,
                role=event.role,
                content=event.content,
                current_branch=session.current_branch,
                external_id=session.external_id,
                model=event.model_used or session.model,
                message_count=message_counts.get(session.id, 0),
                tool_count=tool_counts.get(session.id, 0),
            )
        )

    for session in persona_sessions:
        if session.session_type == "chat":
            continue
        live_summary, live_status = _live_activity_summary(session)
        entries.append(
            PersonaStreamEntry(
                id=f"session-{session.id}",
                entry_type="heartbeat",
                timestamp=session.created_at,
                session_id=session.id,
                parent_session_id=session.parent_session_id,
                project_id=session.project_id,
                agent_slug=session.agent_slug,
                session_type="heartbeat" if session.project_id == "persona-sandbox" else session.session_type,
                status=session.status,
                summary_oneliner=session.summary_oneliner,
                current_branch=session.current_branch,
                external_id=session.external_id,
                model=session.model,
                live_summary=live_summary,
                live_status=live_status,
                message_count=message_counts.get(session.id, 0),
                tool_count=tool_counts.get(session.id, 0),
                event_previews=event_previews.get(session.id, []),
            )
        )

    for session in child_sessions:
        live_summary, live_status = _live_activity_summary(session)
        entries.append(
            PersonaStreamEntry(
                id=f"child-{session.id}",
                entry_type="child_run",
                timestamp=session.created_at,
                session_id=session.id,
                parent_session_id=session.parent_session_id,
                project_id=session.project_id,
                agent_slug=session.agent_slug,
                session_type=session.session_type,
                status=session.status,
                summary_oneliner=session.summary_oneliner,
                current_branch=session.current_branch,
                external_id=session.external_id,
                model=session.model,
                live_summary=live_summary,
                live_status=live_status,
                message_count=message_counts.get(session.id, 0),
                tool_count=tool_counts.get(session.id, 0),
                event_previews=event_previews.get(session.id, []),
            )
        )

    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    return entries


def _slice_entries(
    entries: list[PersonaStreamEntry],
    *,
    page: int,
    page_size: int,
    focus_session_id: str | None,
) -> list[PersonaStreamEntry]:
    if focus_session_id:
        focus_indexes = [idx for idx, entry in enumerate(entries) if entry.session_id == focus_session_id]
        if focus_indexes:
            focus_idx = focus_indexes[0]
            start = max(focus_idx - (page_size // 2), 0)
            end = min(start + page_size, len(entries))
            start = max(end - page_size, 0)
            return entries[start:end]

    offset = (page - 1) * page_size
    return entries[offset : offset + page_size]


@router.get("/stream", response_model=PersonaStreamResponse)
async def get_persona_stream(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="24h", description="Time range: 6h, 24h, 7d, 30d, all"),
    search: str | None = Query(default=None, description="Search across Jenny messages and activity"),
    focus_session_id: str | None = Query(default=None, description="Center the response around a specific session"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
) -> PersonaStreamResponse:
    """Return the unified Jenny stream: chat messages, heartbeats, and child runs."""
    search_term = search.strip() if search else None
    hours = 0 if search_term else HOURS_MAP.get(time_range, 24)

    persona_sessions = list(
        (await db.execute(_persona_session_query(hours, search_term).order_by(Session.created_at.desc()))).scalars().all()
    )
    persona_session_ids = [session.id for session in persona_sessions]

    child_sessions: list[Session] = []
    if persona_session_ids:
        child_sessions = list(
            (
                await db.execute(
                    _child_session_query(persona_session_ids, hours, search_term).order_by(Session.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    count_session_ids = persona_session_ids + [session.id for session in child_sessions]
    message_counts = await _fetch_message_counts(db, count_session_ids)
    tool_counts = await _fetch_tool_counts(db, count_session_ids)
    event_previews = await _fetch_event_previews(db, count_session_ids)
    persona_chat_ids = [session.id for session in persona_sessions if session.session_type == "chat"]
    message_events = await _fetch_persona_chat_events(db, persona_chat_ids, search_term)

    entries = _build_stream_entries(
        persona_sessions,
        child_sessions,
        message_events,
        message_counts,
        tool_counts,
        event_previews,
    )

    sliced_entries = _slice_entries(
        entries,
        page=page,
        page_size=page_size,
        focus_session_id=focus_session_id,
    )
    return PersonaStreamResponse(
        entries=sliced_entries,
        total=len(entries),
        page=page,
        page_size=page_size,
    )
