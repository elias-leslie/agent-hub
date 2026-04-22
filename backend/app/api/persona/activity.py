"""Activity timeline endpoint for the persona API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.session import Session, SessionEvent
from app.services.session_live_activity import (
    build_live_activity_response,
    is_session_actionably_active,
)

from .constants import (
    CONTENT_PREVIEW_LEN,
    EVENT_PREVIEW_LIMIT,
    HOURS_MAP,
)
from .schemas import ActivityEventPreview, ActivityResponse, ActivitySession

router = APIRouter()


def _classify_activity_session_type(session: Session) -> str:
    """Map stored session metadata to the activity view's semantic session type."""
    if session.session_type == "completion" and session.project_id == "persona-sandbox":
        return "heartbeat"
    return session.session_type or "completion"


def _build_session_query(hours: int) -> Select:
    """Return a SELECT for persona sessions, optionally filtered by time.

    Shows persona activity across ALL projects (no hardcoded project filter).
    Projects with permission_tier='off' still generate sessions if persona
    ran before the tier was changed, so we show everything.

    Excludes empty chat sessions (0 events) which are noise from abandoned sessions.
    """
    # Subquery: sessions that have at least one event
    has_events = (
        select(SessionEvent.session_id)
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .exists()
    )
    query = select(Session).where(
        Session.agent_slug == "persona",
        has_events,
    )
    if hours > 0:
        since = datetime.now(UTC) - timedelta(hours=hours)
        query = query.where(Session.created_at >= since)
    return query


async def _fetch_event_previews(
    db: AsyncSession,
    session_ids: list[str],
) -> dict[str, list[ActivityEventPreview]]:
    """Fetch up to EVENT_PREVIEW_LIMIT events per session for preview cards."""
    if not session_ids:
        return {}

    # Use a window function to limit rows in SQL instead of over-fetching
    row_num = (
        func.row_number()
        .over(
            partition_by=SessionEvent.session_id,
            order_by=[SessionEvent.turn, SessionEvent.sequence],
        )
        .label("rn")
    )
    subq = (
        select(SessionEvent, row_num)
        .where(SessionEvent.session_id.in_(session_ids))
        .subquery()
    )
    events_query = (
        select(subq)
        .where(subq.c.rn <= EVENT_PREVIEW_LIMIT)
        .order_by(subq.c.session_id, subq.c.turn, subq.c.sequence)
    )
    rows = (await db.execute(events_query)).all()

    events_by_session: dict[str, list[ActivityEventPreview]] = {}
    for row in rows:
        sid = row.session_id
        preview = row.content[:CONTENT_PREVIEW_LEN] if row.content else None
        events_by_session.setdefault(sid, []).append(
            ActivityEventPreview(
                event_type=row.event_type,
                tool_name=row.tool_name,
                content_preview=preview,
            )
        )
    return events_by_session


async def _fetch_session_counts(
    db: AsyncSession,
    session_ids: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    """Return mappings of session_id → message count and event count."""
    if not session_ids:
        return {}, {}

    msg_count_query = (
        select(
            SessionEvent.session_id,
            func.count().label("cnt"),
        )
        .where(
            SessionEvent.session_id.in_(session_ids),
            SessionEvent.event_type.in_(["user_message", "assistant_message"]),
        )
        .group_by(SessionEvent.session_id)
    )
    event_count_query = (
        select(
            SessionEvent.session_id,
            func.count().label("cnt"),
        )
        .where(SessionEvent.session_id.in_(session_ids))
        .group_by(SessionEvent.session_id)
    )
    return (
        {row.session_id: row.cnt for row in (await db.execute(msg_count_query)).all()},
        {row.session_id: row.cnt for row in (await db.execute(event_count_query)).all()},
    )


async def _fetch_child_counts(
    db: AsyncSession,
    session_ids: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    if not session_ids:
        return {}, {}
    child_result = await db.execute(select(Session).where(Session.parent_session_id.in_(session_ids)))
    child_counts: dict[str, int] = {}
    active_child_counts: dict[str, int] = {}
    for child_session in child_result.scalars().all():
        parent_id = str(child_session.parent_session_id or "").strip()
        if not parent_id:
            continue
        child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
        if is_session_actionably_active(child_session):
            active_child_counts[parent_id] = active_child_counts.get(parent_id, 0) + 1
    return child_counts, active_child_counts




def _status_provenance(session: Session, live: dict[str, object] | None) -> tuple[str, bool]:
    live_status = None if live is None else live.get("status")
    if not live_status:
        return "session", True
    matches = str(live_status) == str(session.status)
    return ("session" if matches or session.status != "active" else "runtime"), matches

@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="24h", description="Time range: 6h, 24h, 7d, 30d, all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ActivityResponse:
    """Get persona activity timeline — chat + heartbeat sessions interleaved chronologically."""
    hours = HOURS_MAP.get(time_range, 24)
    base_query = _build_session_query(hours)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    paginated = base_query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)
    sessions = list((await db.execute(paginated)).scalars().all())

    session_ids = [s.id for s in sessions]
    events_by_session = await _fetch_event_previews(db, session_ids)
    msg_counts, event_counts = await _fetch_session_counts(db, session_ids)
    child_counts, active_child_counts = await _fetch_child_counts(db, session_ids)
    live_map = {session.id: build_live_activity_response(session) for session in sessions}
    activity_sessions: list[ActivitySession] = []
    for session in sessions:
        live = live_map.get(session.id)
        status_source, status_matches_live = _status_provenance(session, live)
        activity_sessions.append(
            ActivitySession(
                id=session.id,
                session_type=_classify_activity_session_type(session),
                summary_oneliner=session.summary_oneliner,
                status=session.status,
                message_count=msg_counts.get(session.id, 0),
                event_count=event_counts.get(session.id),
                child_session_count=child_counts.get(session.id),
                active_child_session_count=active_child_counts.get(session.id),
                status_source=status_source,
                status_matches_live=status_matches_live,
                live_status=None if live is None else str(live.get("status") or ""),
                live_source=None if live is None else str(live.get("source") or "runtime"),
                created_at=session.created_at,
                updated_at=session.updated_at,
                events_preview=events_by_session.get(session.id, []),
            )
        )

    return ActivityResponse(
        sessions=activity_sessions,
        total=total,
        page=page,
        page_size=page_size,
    )
