"""Database queries for continuity injection.

Handles querying session summaries from both:
- SessionSummarySegment table (post-migration)
- Session summary columns (legacy/pre-migration)

Also provides cross-project and active session queries for
enriched continuity context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Session, SessionEvent, SessionSummarySegment
from app.services.memory._continuity_segments import (
    query_from_segments,
    query_from_session_columns,
)

_SummaryDict = dict[str, Any]

# Re-export helpers so existing callers that may import them directly keep working
__all__ = [
    "query_active_sessions",
    "query_cross_project_summaries",
    "query_from_segments",
    "query_from_session_columns",
    "query_recent_summaries",
]


async def query_recent_summaries(
    db: AsyncSession,
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
    staleness_cutoff: datetime,
) -> list[_SummaryDict]:
    """Query recent summaries from segments table, falling back to session columns.

    Primary path: query SessionSummarySegment rows (one per work period),
    joined with Session for metadata (agent_slug, project_id).

    Fallback: for pre-migration sessions that have summary columns but no
    segments, supplement with session-column data.

    Applies branch scoping, outcome filtering, and staleness check.
    """
    summaries = await query_from_segments(
        db, project_id, current_branch, max_sessions, staleness_cutoff
    )

    if len(summaries) >= max_sessions:
        return summaries[:max_sessions]

    covered_session_ids = {str(s["session_id"]) for s in summaries}
    legacy = await query_from_session_columns(
        db,
        project_id,
        current_branch,
        max_sessions,
        staleness_cutoff,
        exclude_session_ids=covered_session_ids,
    )
    summaries.extend(legacy[: max_sessions - len(summaries)])

    summaries.sort(key=lambda s: s["created_at"], reverse=True)
    return summaries[:max_sessions]


async def query_cross_project_summaries(
    db: AsyncSession,
    exclude_project_id: str,
    max_entries: int,
    staleness_cutoff: datetime,
) -> list[_SummaryDict]:
    """Query recent summaries from OTHER projects for cross-project awareness.

    Excludes the current project and returns the most recent summary per
    session from other projects the user is active in.
    """
    seg = aliased(SessionSummarySegment)

    query = (
        select(
            seg.session_id,
            Session.agent_slug,
            Session.project_id,
            seg.summary_oneliner,
            seg.summary_outcome,
            seg.created_at,
        )
        .distinct(seg.session_id)
        .join(Session, seg.session_id == Session.id)
        .where(
            and_(
                seg.created_at > staleness_cutoff,
                Session.project_id != exclude_project_id,
                or_(
                    seg.summary_outcome != "abandoned",
                    seg.summary_outcome.is_(None),
                ),
            )
        )
        .order_by(seg.session_id, seg.created_at.desc())
        .limit(max_entries)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.session_id,
            "agent_slug": row.agent_slug,
            "project_id": row.project_id,
            "summary": row.summary_oneliner,
            "outcome": row.summary_outcome,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def query_active_sessions(
    db: AsyncSession,
    project_id: str | None = None,
    exclude_session_id: str | None = None,
    max_entries: int = 5,
) -> list[_SummaryDict]:
    """Query currently active sessions for live awareness.

    Returns active sessions started within the last 24 hours,
    excluding truly stale sessions and the current session.

    Ghost filter: excludes sessions with 0 events that are older
    than 15 minutes (registered but never used).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    ghost_cutoff = datetime.now(UTC) - timedelta(minutes=15)

    conditions: list[Any] = [
        Session.status == "active",
        Session.created_at > cutoff,
    ]

    if project_id:
        conditions.append(Session.project_id == project_id)

    if exclude_session_id:
        conditions.append(Session.id != exclude_session_id)

    event_count = (
        select(func.count(SessionEvent.id))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .scalar_subquery()
    )

    # Ghost filter: sessions must have events OR be less than 15 minutes old
    conditions.append(
        or_(event_count > 0, Session.created_at > ghost_cutoff)
    )

    # Correlated subquery: most recent Write/Edit tool_use event's file_path
    write_edit_event = aliased(SessionEvent)
    last_touched_file = (
        select(
            func.cast(write_edit_event.tool_input["file_path"], String(500))
        )
        .where(
            and_(
                write_edit_event.session_id == Session.id,
                write_edit_event.event_type == "tool_use",
                write_edit_event.tool_name.in_(["Write", "Edit"]),
            )
        )
        .correlate(Session)
        .order_by(write_edit_event.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    query = (
        select(
            Session.id,
            Session.agent_slug,
            Session.project_id,
            Session.external_id,
            Session.created_at,
            event_count.label("event_count"),
            last_touched_file.label("last_touched_file"),
        )
        .where(and_(*conditions))
        .order_by(Session.created_at.desc())
        .limit(max_entries)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.id,
            "agent_slug": row.agent_slug,
            "project_id": row.project_id,
            "external_id": row.external_id,
            "created_at": row.created_at,
            "event_count": row.event_count,
            "last_touched_file": row.last_touched_file,
        }
        for row in rows
    ]
