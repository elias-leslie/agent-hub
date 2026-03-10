"""Unified timeline endpoint for the persona workspace."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.session import Session, SessionEvent

from .constants import HOURS_MAP
from .pulse import build_pulse_summary, build_session_pulses
from .schemas import (
    PersonaStreamEntry,
    PersonaStreamEventPreview,
    PersonaStreamMatch,
    PersonaStreamResponse,
)

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
_STRUCTURED_PREFIXES = {"task", "file", "agent", "status", "project"}
_ISSUE_SIGNAL_TERMS = (
    "error",
    "failed",
    "failure",
    "warning",
    "blocked",
    "stalled",
    "waiting",
    "retry",
    "retried",
    "permission denied",
    "timed out",
    "timeout",
    "not found",
    "missing",
    "interrupted",
)


@dataclass(slots=True)
class ParsedSearch:
    general_terms: list[str] = field(default_factory=list)
    task_terms: list[str] = field(default_factory=list)
    file_terms: list[str] = field(default_factory=list)
    agent_terms: list[str] = field(default_factory=list)
    status_terms: list[str] = field(default_factory=list)
    project_terms: list[str] = field(default_factory=list)

    def has_terms(self) -> bool:
        return any(
            [
                self.general_terms,
                self.task_terms,
                self.file_terms,
                self.agent_terms,
                self.status_terms,
                self.project_terms,
            ]
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


def _entry_match_text(entry: PersonaStreamEntry) -> str:
    return " ".join(
        value
        for value in [
            entry.content,
            entry.summary_oneliner,
            entry.live_summary,
            entry.agent_slug,
            entry.project_id,
            entry.external_id,
            entry.current_branch,
            entry.model,
            *[
                preview_value
                for preview in entry.event_previews
                for preview_value in [
                    preview.tool_name,
                    preview.content_preview,
                    preview.tool_input_preview,
                    preview.tool_output_preview,
                    preview.model_used,
                    preview.event_type,
                ]
                if isinstance(preview_value, str)
            ],
            *[
                marker_value
                for marker in entry.issue_markers
                for marker_value in [
                    marker.title,
                    marker.summary,
                    marker.tool_name,
                    marker.primary_tag,
                    marker.primary_root_cause,
                ]
                if isinstance(marker_value, str)
            ],
        ]
        if isinstance(value, str) and value
    ).lower()


def _parse_search(search: str | None) -> ParsedSearch:
    parsed = ParsedSearch()
    if not search:
        return parsed

    for raw_token in search.split():
        token = raw_token.strip()
        if not token:
            continue
        prefix, separator, value = token.partition(":")
        normalized_prefix = prefix.lower()
        normalized_value = value.strip().lower()
        if separator and normalized_prefix in _STRUCTURED_PREFIXES and normalized_value:
            getattr(parsed, f"{normalized_prefix}_terms").append(normalized_value)
            continue
        parsed.general_terms.append(token.lower())
    return parsed


def _matches_terms(text: str, terms: list[str]) -> bool:
    return all(term in text for term in terms)


def _entry_matches_search(entry: PersonaStreamEntry, parsed_search: ParsedSearch) -> bool:
    if not parsed_search.has_terms():
        return False
    entry_text = _entry_match_text(entry)
    if parsed_search.general_terms and not _matches_terms(entry_text, parsed_search.general_terms):
        return False

    if parsed_search.task_terms:
        task_text = " ".join(
            value.lower()
            for value in [entry.external_id, entry.summary_oneliner, entry.live_summary, entry.content]
            if isinstance(value, str) and value
        )
        if not _matches_terms(task_text, parsed_search.task_terms):
            return False

    if parsed_search.file_terms and not _matches_terms(entry_text, parsed_search.file_terms):
        return False

    if parsed_search.agent_terms:
        agent_text = " ".join(
            value.lower()
            for value in [entry.agent_slug, entry.summary_oneliner, entry.live_summary]
            if isinstance(value, str) and value
        )
        if not _matches_terms(agent_text, parsed_search.agent_terms):
            return False

    if parsed_search.status_terms:
        status_text = " ".join(
            value.lower()
            for value in [entry.status, entry.live_status, entry.summary_oneliner, entry.live_summary]
            if isinstance(value, str) and value
        )
        if not _matches_terms(status_text, parsed_search.status_terms):
            return False

    if parsed_search.project_terms:
        project_text = " ".join(
            value.lower()
            for value in [entry.project_id, entry.current_branch, entry.summary_oneliner]
            if isinstance(value, str) and value
        )
        if not _matches_terms(project_text, parsed_search.project_terms):
            return False

    return True


def _entry_match_snippet(entry: PersonaStreamEntry) -> str:
    for value in [
        entry.content,
        entry.summary_oneliner,
        entry.live_summary,
        *[preview.content_preview for preview in entry.event_previews],
        *[preview.tool_name for preview in entry.event_previews],
    ]:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{entry.entry_type} in {entry.project_id}"


def _event_match_predicate(term: str) -> Any:
    wildcard = f"%{term}%"
    return (
        select(SessionEvent.id)
        .where(
            SessionEvent.session_id == Session.id,
            SessionEvent.event_type.in_(_SEARCHABLE_EVENT_TYPES),
            or_(
                SessionEvent.content.ilike(wildcard),
                SessionEvent.tool_name.ilike(wildcard),
                cast(SessionEvent.tool_input, String).ilike(wildcard),
                cast(SessionEvent.tool_output, String).ilike(wildcard),
            ),
        )
        .correlate(Session)
        .exists()
    )


def _session_search_predicates(parsed_search: ParsedSearch) -> list[Any]:
    predicates: list[Any] = []

    for term in parsed_search.general_terms:
        wildcard = f"%{term}%"
        predicates.append(
            or_(
                Session.summary_oneliner.ilike(wildcard),
                Session.project_id.ilike(wildcard),
                Session.agent_slug.ilike(wildcard),
                Session.external_id.ilike(wildcard),
                Session.current_branch.ilike(wildcard),
                _event_match_predicate(term),
            )
        )

    for term in parsed_search.task_terms:
        wildcard = f"%{term}%"
        predicates.append(
            or_(
                Session.external_id.ilike(wildcard),
                Session.summary_oneliner.ilike(wildcard),
                _event_match_predicate(term),
            )
        )

    for term in parsed_search.file_terms:
        predicates.append(_event_match_predicate(term))

    for term in parsed_search.agent_terms:
        wildcard = f"%{term}%"
        predicates.append(
            or_(
                Session.agent_slug.ilike(wildcard),
                Session.summary_oneliner.ilike(wildcard),
                _event_match_predicate(term),
            )
        )

    for term in parsed_search.status_terms:
        wildcard = f"%{term}%"
        predicates.append(
            or_(
                Session.status.ilike(wildcard),
                Session.summary_oneliner.ilike(wildcard),
                _event_match_predicate(term),
            )
        )

    for term in parsed_search.project_terms:
        wildcard = f"%{term}%"
        predicates.append(
            or_(
                Session.project_id.ilike(wildcard),
                Session.current_branch.ilike(wildcard),
                Session.summary_oneliner.ilike(wildcard),
                _event_match_predicate(term),
            )
        )
    return predicates


def _persona_session_query(hours: int, parsed_search: ParsedSearch | None) -> Select:
    has_events = (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )
    query = select(Session).where(Session.agent_slug == "persona", has_events)
    query = _apply_since(query, hours)
    if parsed_search and parsed_search.has_terms():
        query = query.where(and_(*_session_search_predicates(parsed_search)))
    return query


def _child_session_query(persona_session_ids: Iterable[str], hours: int, parsed_search: ParsedSearch | None) -> Select:
    ids = list(persona_session_ids)
    query = select(Session).where(
        Session.parent_session_id.in_(ids),
        Session.agent_slug.isnot(None),
        Session.agent_slug != "persona",
    )
    query = _apply_since(query, hours)
    if parsed_search and parsed_search.has_terms():
        query = query.where(and_(*_session_search_predicates(parsed_search)))
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


def _event_has_issue_signal(event: SessionEvent) -> bool:
    if event.event_type == "error":
        return True
    combined = " ".join(
        part
        for part in [
            _stringify_preview(event.content, limit=None),
            _stringify_preview(event.tool_input, limit=None),
            _stringify_preview(event.tool_output, limit=None),
            event.tool_name,
            event.role,
        ]
        if isinstance(part, str) and part
    ).lower()
    return any(term in combined for term in _ISSUE_SIGNAL_TERMS)


def _stringify_preview(value: Any, *, limit: int | None = 280) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except TypeError:
            text = str(value)
    if limit is None or len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _build_stream_entries(
    persona_sessions: list[Session],
    child_sessions: list[Session],
    message_events: list[SessionEvent],
    message_counts: dict[str, int],
    tool_counts: dict[str, int],
    event_previews: dict[str, list[PersonaStreamEventPreview]],
    session_pulses: dict[str, Any] | None = None,
) -> list[PersonaStreamEntry]:
    persona_by_id = {session.id: session for session in persona_sessions}
    entries: list[PersonaStreamEntry] = []
    session_pulses = session_pulses or {}

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
        pulse = session_pulses.get(session.id)
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
                issue_markers=pulse.issue_markers if pulse else [],
                pulse_tags=pulse.tags if pulse else [],
                primary_pulse_tag=pulse.primary_tag if pulse else None,
                root_causes=pulse.root_causes if pulse else [],
                primary_root_cause=pulse.primary_root_cause if pulse else None,
                pulse_summary=pulse.summary if pulse else None,
            )
        )

    for session in child_sessions:
        live_summary, live_status = _live_activity_summary(session)
        pulse = session_pulses.get(session.id)
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
                issue_markers=pulse.issue_markers if pulse else [],
                pulse_tags=pulse.tags if pulse else [],
                primary_pulse_tag=pulse.primary_tag if pulse else None,
                root_causes=pulse.root_causes if pulse else [],
                primary_root_cause=pulse.primary_root_cause if pulse else None,
                pulse_summary=pulse.summary if pulse else None,
            )
        )

    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    return entries


def _build_search_matches(
    entries: list[PersonaStreamEntry],
    *,
    parsed_search: ParsedSearch,
    limit: int = 150,
) -> tuple[list[PersonaStreamMatch], int]:
    if not parsed_search.has_terms():
        return [], 0
    matches: list[PersonaStreamMatch] = []
    total_matches = 0
    for entry in entries:
        if not _entry_matches_search(entry, parsed_search):
            continue
        total_matches += 1
        if len(matches) < limit:
            matches.append(
                PersonaStreamMatch(
                    entry_id=entry.id,
                    session_id=entry.session_id,
                    entry_type=entry.entry_type,
                    timestamp=entry.timestamp,
                    snippet=_entry_match_snippet(entry),
                )
            )
    return matches, total_matches


def _slice_entries(
    entries: list[PersonaStreamEntry],
    *,
    page: int,
    page_size: int,
    focus_session_id: str | None,
    anchor_entry_id: str | None,
) -> list[PersonaStreamEntry]:
    if anchor_entry_id:
        anchor_indexes = [idx for idx, entry in enumerate(entries) if entry.id == anchor_entry_id]
        if anchor_indexes:
            anchor_idx = anchor_indexes[0]
            start = max(anchor_idx - (page_size // 2), 0)
            end = min(start + page_size, len(entries))
            start = max(end - page_size, 0)
            return entries[start:end]

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
    anchor_entry_id: str | None = Query(default=None, description="Center the response around a specific entry"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
) -> PersonaStreamResponse:
    """Return the unified Jenny stream: chat messages, heartbeats, and child runs."""
    search_term = search.strip() if search else None
    parsed_search = _parse_search(search_term)
    hours = 0 if search_term else HOURS_MAP.get(time_range, 24)

    persona_sessions = list(
        (await db.execute(_persona_session_query(hours, parsed_search).order_by(Session.created_at.desc()))).scalars().all()
    )
    persona_session_ids = [session.id for session in persona_sessions]

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

    count_session_ids = persona_session_ids + [session.id for session in child_sessions]
    message_counts = await _fetch_message_counts(db, count_session_ids)
    tool_counts = await _fetch_tool_counts(db, count_session_ids)
    event_previews = await _fetch_event_previews(db, count_session_ids)
    persona_chat_ids = [session.id for session in persona_sessions if session.session_type == "chat"]
    message_events = await _fetch_persona_chat_events(db, persona_chat_ids)
    session_pulses = build_session_pulses([*persona_sessions, *child_sessions], event_previews)

    entries = _build_stream_entries(
        persona_sessions,
        child_sessions,
        message_events,
        message_counts,
        tool_counts,
        event_previews,
        session_pulses,
    )
    matches, match_count = _build_search_matches(entries, parsed_search=parsed_search)
    pulse = build_pulse_summary(entries, [*persona_sessions, *child_sessions], session_pulses)

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
