"""Database queries for continuity injection.

Handles querying session summaries from both:
- SessionSummarySegment table (post-migration)
- Session summary columns (legacy/pre-migration)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from app.models import Session, SessionSummarySegment


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
        .join(Session, seg.session_id == Session.id)
        .where(and_(*conditions))
        .order_by(seg.created_at.desc())
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
