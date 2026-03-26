"""Unified timeline endpoint for the persona workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.session import Session, SessionEvent
from app.services.session_display_summary import (
    SessionDisplaySummaryCandidate,
    fetch_session_display_summaries,
)

from .constants import HOURS_MAP
from .pulse import build_pulse_summary, build_session_pulses
from .schemas import PersonaStreamEventPreview, PersonaStreamResponse
from .stream_builders import (
    _build_stream_entries,
    _event_has_issue_signal,
    _live_activity_summary,
    _stringify_preview,
)
from .stream_queries import _child_session_query, _persona_session_query
from .stream_search import ParsedSearch, _build_search_matches, _parse_search, _slice_entries

router = APIRouter()

_CHAT_MESSAGE_TYPES = ("user_message", "assistant_message")


async def _fetch_event_counts(
    db: AsyncSession,
    session_ids: list[str],
    event_types: tuple[str, ...],
) -> dict[str, int]:
    if not session_ids:
        return {}
    query = (
        select(SessionEvent.session_id, func.count().label("cnt"))
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(event_types),
        )
        .group_by(SessionEvent.session_id)
    )
    return {row.session_id: row.cnt for row in (await db.execute(query)).all()}


async def _fetch_persona_chat_events(
    db: AsyncSession,
    session_ids: list[str],
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
        preserve_full_text = _event_has_issue_signal(event)
        preview_content = _stringify_preview(event.content, limit=None if preserve_full_text else 240)
        session_previews.append(
            PersonaStreamEventPreview(
                id=event.id,
                event_type=event.event_type,
                created_at=event.created_at,
                role=event.role,
                tool_name=event.tool_name,
                content_preview=preview_content,
                tool_input_preview=_stringify_preview(event.tool_input, limit=None if preserve_full_text else 280),
                tool_output_preview=_stringify_preview(event.tool_output, limit=None if preserve_full_text else 280),
                duration_ms=event.duration_ms,
                model_used=event.model_used,
            )
        )
    return previews


async def _fetch_display_summaries(
    db: AsyncSession,
    sessions: list[Session],
) -> dict[str, str | None]:
    candidates = [
        SessionDisplaySummaryCandidate(
            session_id=session.id,
            summary_oneliner=session.summary_oneliner,
            live_summary=_live_activity_summary(session)[0],
        )
        for session in sessions
        if session.session_type != "chat"
    ]
    return await fetch_session_display_summaries(db, candidates)


async def _fetch_sessions(
    db: AsyncSession,
    hours: int,
    parsed_search: ParsedSearch,
) -> tuple[list[Session], list[Session]]:
    """Fetch persona sessions and their child sessions."""
    persona_sessions = list(
        (await db.execute(_persona_session_query(hours, parsed_search).order_by(Session.created_at.desc()))).scalars().all()
    )
    persona_session_ids = [s.id for s in persona_sessions]
    child_sessions: list[Session] = []
    if persona_session_ids:
        child_sessions = list(
            (
                await db.execute(
                    _child_session_query(persona_session_ids, hours, parsed_search).order_by(Session.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return persona_sessions, child_sessions


@router.get("/stream", response_model=PersonaStreamResponse)
async def get_persona_stream(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="24h", description="Time range: 6h, 24h, 7d, 30d, all"),
    search: str | None = Query(default=None, description="Search across persona messages and activity"),
    focus_session_id: str | None = Query(default=None, description="Center the response around a specific session"),
    anchor_entry_id: str | None = Query(default=None, description="Center the response around a specific entry"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
) -> PersonaStreamResponse:
    """Return the unified persona stream: chat messages, heartbeats, and child runs."""
    search_term = search.strip() if search else None
    parsed_search = _parse_search(search_term)
    hours = 0 if search_term else HOURS_MAP.get(time_range, 24)

    persona_sessions, child_sessions = await _fetch_sessions(db, hours, parsed_search)
    all_session_ids = [s.id for s in persona_sessions] + [s.id for s in child_sessions]

    message_counts = await _fetch_event_counts(db, all_session_ids, _CHAT_MESSAGE_TYPES)
    tool_counts = await _fetch_event_counts(db, all_session_ids, ("tool_use",))
    event_previews = await _fetch_event_previews(db, all_session_ids)
    persona_chat_ids = [s.id for s in persona_sessions if s.session_type == "chat"]
    message_events = await _fetch_persona_chat_events(db, persona_chat_ids)
    all_sessions = [*persona_sessions, *child_sessions]
    session_pulses = build_session_pulses(all_sessions, event_previews)
    display_summaries = await _fetch_display_summaries(db, all_sessions)

    entries = _build_stream_entries(
        persona_sessions, child_sessions, message_events,
        message_counts, tool_counts, event_previews, session_pulses, display_summaries,
    )
    matches, match_count = _build_search_matches(entries, parsed_search=parsed_search)
    pulse = build_pulse_summary(entries, all_sessions, session_pulses)

    sliced_entries = _slice_entries(
        entries,
        page=page,
        page_size=page_size,
        focus_session_id=focus_session_id,
        anchor_entry_id=anchor_entry_id,
    )
    return PersonaStreamResponse(
        entries=sliced_entries,
        total=len(entries),
        page=page,
        page_size=page_size,
        matches=matches,
        match_count=match_count,
        pulse=pulse,
    )
