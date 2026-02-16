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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Session, SessionEvent, SessionSummarySegment


async def query_recent_summaries(
    db: Any,
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
    staleness_cutoff: datetime,
) -> list[dict[str, Any]]:
    """Query recent summaries from segments table, falling back to session columns.

    Primary path: query SessionSummarySegment rows (one per work period),
    joined with Session for metadata (agent_slug, project_id).

    Fallback: for pre-migration sessions that have summary columns but no
    segments, supplement with session-column data.

    Applies branch scoping, outcome filtering, and staleness check.
    """
    # Primary: query from segments table (post-migration data)
    summaries = await query_from_segments(
        db, project_id, current_branch, max_sessions, staleness_cutoff
    )

    if len(summaries) < max_sessions:
        # Supplement with session-column data (pre-migration sessions)
        covered_session_ids = {s["session_id"] for s in summaries}
        legacy = await query_from_session_columns(
            db,
            project_id,
            current_branch,
            max_sessions,
            staleness_cutoff,
            exclude_session_ids=covered_session_ids,
        )
        summaries.extend(legacy[: max_sessions - len(summaries)])

    # Sort combined results by created_at descending
    summaries.sort(key=lambda s: s["created_at"], reverse=True)
    return summaries[:max_sessions]


async def query_from_segments(
    db: Any,
    project_id: str | None,
    current_branch: str | None,
    max_entries: int,
    staleness_cutoff: datetime,
) -> list[dict[str, Any]]:
    """Query summary segments joined with sessions for metadata."""
    seg = aliased(SessionSummarySegment)

    conditions: list[Any] = [
        seg.created_at > staleness_cutoff,
        or_(
            seg.summary_outcome != "abandoned",
            seg.summary_outcome.is_(None),
        ),
    ]

    if project_id:
        conditions.append(Session.project_id == project_id)

    if current_branch:
        conditions.append(
            or_(
                seg.summary_branch.is_(None),
                seg.summary_branch.in_(["main", "master", current_branch]),
                seg.summary_is_worktree == False,  # noqa: E712
            )
        )

    # DISTINCT ON session_id: pick most recent segment per session
    # to prevent one session's many segments from filling all slots
    query = (
        select(
            seg.session_id,
            Session.agent_slug,
            seg.summary_oneliner,
            seg.summary_outcome,
            seg.summary_branch,
            seg.summary_is_worktree,
            seg.summary_git_digest,
            seg.created_at,
        )
        .distinct(seg.session_id)
        .join(Session, seg.session_id == Session.id)
        .where(and_(*conditions))
        .order_by(seg.session_id, seg.created_at.desc())
        .limit(max_entries)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.session_id,
            "agent_slug": row.agent_slug,
            "summary": row.summary_oneliner,
            "outcome": row.summary_outcome,
            "branch": row.summary_branch,
            "is_worktree": row.summary_is_worktree,
            "git_digest": row.summary_git_digest,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def query_from_session_columns(
    db: Any,
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
    staleness_cutoff: datetime,
    *,
    exclude_session_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Fallback: query session-level summary columns for pre-migration data."""
    conditions: list[Any] = [
        Session.summary_oneliner.isnot(None),
        or_(
            Session.summary_outcome != "abandoned",
            Session.summary_outcome.is_(None),
        ),
        Session.summary_generated_at > staleness_cutoff,
    ]

    if project_id:
        conditions.append(Session.project_id == project_id)

    if current_branch:
        conditions.append(
            or_(
                Session.summary_branch.is_(None),
                Session.summary_branch.in_(["main", "master", current_branch]),
                Session.summary_is_worktree == False,  # noqa: E712
            )
        )

    if exclude_session_ids:
        conditions.append(Session.id.notin_(exclude_session_ids))

    query = (
        select(
            Session.id,
            Session.agent_slug,
            Session.summary_oneliner,
            Session.summary_outcome,
            Session.summary_branch,
            Session.summary_is_worktree,
            Session.summary_git_digest,
            Session.created_at,
        )
        .where(and_(*conditions))
        .order_by(Session.created_at.desc())
        .limit(max_sessions)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.id,
            "agent_slug": row.agent_slug,
            "summary": row.summary_oneliner,
            "outcome": row.summary_outcome,
            "branch": row.summary_branch,
            "is_worktree": row.summary_is_worktree,
            "git_digest": row.summary_git_digest,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def query_cross_project_summaries(
    db: AsyncSession,
    exclude_project_id: str,
    max_entries: int,
    staleness_cutoff: datetime,
) -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
    """Query currently active sessions for live awareness.

    Returns active sessions started within the last 24 hours,
    excluding truly stale sessions and the current session.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    conditions: list[Any] = [
        Session.status == "active",
        Session.created_at > cutoff,
    ]

    if project_id:
        conditions.append(Session.project_id == project_id)

    if exclude_session_id:
        conditions.append(Session.id != exclude_session_id)

    # Subquery for event counts
    event_count = (
        select(func.count(SessionEvent.id))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .scalar_subquery()
    )

    query = (
        select(
            Session.id,
            Session.agent_slug,
            Session.project_id,
            Session.created_at,
            event_count.label("event_count"),
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
            "created_at": row.created_at,
            "event_count": row.event_count,
        }
        for row in rows
    ]
