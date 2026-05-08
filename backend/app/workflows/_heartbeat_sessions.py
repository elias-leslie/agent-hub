"""Active session querying and formatting helpers for heartbeat prompts.

Note: _fetch_recently_completed_sessions_section and _get_active_specialist_inventory
live in _heartbeat_data to keep test patch paths at app.workflows._heartbeat_data.*
valid (they call fetch_session_display_summary_results / _query_active_specialist_sessions
which tests patch at _heartbeat_data).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.services.ownership_lanes import infer_task_id
from app.workflows._heartbeat_state import (
    _ACTIVE_SESSION_DISPLAY_LIMIT,
    _ACTIVE_SESSION_GHOST_MINUTES,
    _ACTIVE_SESSION_LOOKBACK_HOURS,
    _ACTIVE_SESSION_PREFILTER_LIMIT,
    _ACTIVE_SPECIALIST_LOOKBACK_HOURS,
    _CODING_AGENT_SESSION_STALE_MINUTES,
    _DEFAULT_SESSION_STALE_MINUTES,
)

logger = logging.getLogger(__name__)


def _session_stale_threshold_minutes(is_coding_agent: bool | None) -> int:
    """Return the stale-session threshold for an agent."""
    if is_coding_agent:
        return _CODING_AGENT_SESSION_STALE_MINUTES
    return _DEFAULT_SESSION_STALE_MINUTES


def _session_display_health(health_detail: str | None, *, is_stale: bool) -> str:
    """Return the display health label for a heartbeat row."""
    in_flight = health_detail is not None and (
        health_detail == "calling_model" or health_detail.startswith("executing_tool:")
    )
    if is_stale and not in_flight:
        return "idle"
    return health_detail or "idle"


def _format_age_str(last_activity_at: object, now: datetime) -> str:
    """Format a last-activity timestamp as a human-readable age string."""
    if not isinstance(last_activity_at, datetime):
        return "unknown"
    normalized = (
        last_activity_at.replace(tzinfo=UTC)
        if last_activity_at.tzinfo is None
        else last_activity_at.astimezone(UTC)
    )
    seconds = max(int((now - normalized).total_seconds()), 0)
    minutes = seconds // 60
    if seconds < 60:
        return f"{seconds}s ago"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def _format_active_session_entry(session: dict[str, object], *, now: datetime) -> str:
    """Format one active-session heartbeat row."""
    is_stale = bool(session.get("is_stale"))
    task_ref = session.get("task_ref") or "-"
    _hd_raw = session.get("health_detail")
    health_detail: str | None = _hd_raw if isinstance(_hd_raw, str) else None
    age_str = _format_age_str(session.get("last_activity_at"), now)
    parts = [
        str(session.get("agent_slug") or "session"),
        str(task_ref),
        _session_display_health(health_detail, is_stale=is_stale),
        age_str,
        f"turn {int(session.get('turn_count') or 0)}",
    ]
    in_flight = health_detail is not None and (
        health_detail == "calling_model" or health_detail.startswith("executing_tool:")
    )
    if is_stale and not in_flight:
        parts.append("STALE")
    return f"- {' | '.join(parts)}"


def _map_active_session_row(
    session: object,
    *,
    is_coding_agent: bool | None,
    turn_count: int | None,
    now: datetime,
) -> dict[str, object]:
    """Map a live session row to an active-session dict with staleness metadata."""
    last_activity_at = getattr(session, "last_activity_at", None) or getattr(session, "created_at", now)
    threshold = _session_stale_threshold_minutes(is_coding_agent)
    idle_minutes = max(int((now - last_activity_at).total_seconds() / 60), 0)
    return {
        "agent_slug": getattr(session, "agent_slug", None),
        "task_ref": (
            infer_task_id(
                getattr(session, "external_id", None),
                getattr(session, "current_branch", None),
            )
            or getattr(session, "external_id", None)
            or getattr(session, "current_branch", None)
        ),
        "health_detail": getattr(session, "health_detail", None),
        "last_activity_at": last_activity_at,
        "turn_count": int(turn_count or 0),
        "idle_minutes": idle_minutes,
        "is_stale": idle_minutes >= threshold,
    }


async def _query_active_sessions(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, object]], datetime]:
    """Query actionable active sessions from DB; returns (mapped sessions, now)."""
    from sqlalchemy import and_, func, or_, select

    from app.db import async_session
    from app.models import Agent, Session, SessionEvent
    from app.services.session_live_activity import is_session_actionably_active

    collected_at = now or datetime.now(UTC)
    cutoff = collected_at - timedelta(hours=_ACTIVE_SESSION_LOOKBACK_HOURS)
    ghost_cutoff = collected_at - timedelta(minutes=_ACTIVE_SESSION_GHOST_MINUTES)
    event_subq = (
        select(func.count(SessionEvent.id))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session).scalar_subquery()
    )
    turn_subq = (
        select(func.max(SessionEvent.turn))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session).scalar_subquery()
    )
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Session, Agent.is_coding_agent, turn_subq.label("turn_count"))
                .outerjoin(Agent, Agent.slug == Session.agent_slug)
                .where(and_(
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.created_at >= cutoff,
                    or_(event_subq > 0, Session.created_at >= ghost_cutoff),
                    Session.project_id == target_project_id if target_project_id else True,
                ))
                .order_by(func.coalesce(Session.last_activity_at, Session.created_at).desc())
                .limit(_ACTIVE_SESSION_PREFILTER_LIMIT)
            )
        ).all()
        sessions = [
            _map_active_session_row(
                session, is_coding_agent=is_coding_agent,
                turn_count=turn_count_value, now=collected_at,
            )
            for session, is_coding_agent, turn_count_value in rows
            if is_session_actionably_active(session)
        ]
    return sessions[:_ACTIVE_SESSION_DISPLAY_LIMIT], collected_at


async def _query_active_sessions_for_heartbeat(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Query and map active sessions for heartbeat display."""
    sessions, _ = await _query_active_sessions(target_project_id, now=now)
    return sessions


async def _query_active_specialist_sessions(
    target_project_id: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Query active specialist sessions and return as dicts with age_minutes."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session
    from app.services.persona_identity import PERSONA_SLUG
    from app.services.session_live_activity import is_session_actionably_active

    collected_at = now or datetime.now(UTC)
    cutoff = collected_at - timedelta(hours=_ACTIVE_SPECIALIST_LOOKBACK_HOURS)
    async with async_session() as db:
        raw_rows = (
            await db.execute(
                select(Session)
                .where(and_(
                    Session.status == "active",
                    Session.agent_slug.isnot(None),
                    Session.agent_slug != PERSONA_SLUG,
                    Session.project_id != "persona-sandbox",
                    Session.project_id == target_project_id if target_project_id else True,
                    Session.created_at >= cutoff,
                    Session.external_id.is_(None),
                    Session.current_branch.is_(None),
                ))
                .order_by(Session.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        return [
            {
                "session_id": row.id,
                "agent_slug": row.agent_slug,
                "project_id": row.project_id,
                "parent_session_id": row.parent_session_id,
                "request_source": row.request_source,
                "created_at": row.created_at,
                "age_minutes": int((collected_at - row.created_at).total_seconds() / 60),
            }
            for row in raw_rows
            if row.agent_slug != PERSONA_SLUG
            if is_session_actionably_active(row, has_specialist_lane=True)
        ]


def _format_specialist_group_line(
    project_id: str,
    agent_slug: str,
    group_rows: list[dict[str, object]],
) -> str:
    """Format one specialist group as a single inventory line."""
    session_ids = [str(r["session_id"]) for r in group_rows if r.get("session_id")]
    parent_ids = {str(r["parent_session_id"]) for r in group_rows if r.get("parent_session_id")}
    request_sources = {str(r["request_source"]) for r in group_rows if r.get("request_source")}
    oldest_age = max(int(r.get("age_minutes", 0)) for r in group_rows)
    newest_age = min(int(r.get("age_minutes", 0)) for r in group_rows)
    duplicate = len(group_rows) > 1
    parts = [
        f"- {project_id} | {agent_slug}",
        f"active={len(group_rows)}",
        f"age={newest_age}-{oldest_age}m" if duplicate else f"age={oldest_age}m",
        "next=dedupe_or_wait" if duplicate else "next=wait_or_complement",
    ]
    if request_sources:
        parts.append(f"source={','.join(sorted(request_sources))}")
    if parent_ids:
        parts.append(f"parents={len(parent_ids)}")
    if session_ids:
        parts.append(f"sessions={','.join(session_ids[:2])}")
    return " | ".join(parts)
