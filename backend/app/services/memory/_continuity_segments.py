"""Internal helpers for querying session summary segments and legacy columns.

These functions are implementation details of continuity_query.py and
should not be imported directly by external callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Session, SessionSummarySegment

_SummaryDict = dict[str, Any]


async def query_from_segments(
    db: AsyncSession,
    project_id: str | None,
    current_branch: str | None,
    max_entries: int,
    staleness_cutoff: datetime,
) -> list[_SummaryDict]:
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
            )
        )

    # Two-step query: DISTINCT ON picks most recent segment per session,
    # then outer query sorts by recency and applies LIMIT.
    # Without the subquery, LIMIT applies in session_id alphabetical order
    # (PostgreSQL requires ORDER BY to start with DISTINCT ON columns),
    # which drops recent sessions with high-valued UUIDs.
    inner = (
        select(
            seg.session_id,
            Session.agent_slug,
            seg.summary_oneliner,
            seg.summary_outcome,
            seg.summary_branch,
            seg.summary_git_digest,
            seg.created_at,
        )
        .distinct(seg.session_id)
        .join(Session, seg.session_id == Session.id)
        .where(and_(*conditions))
        .order_by(seg.session_id, seg.created_at.desc())
    ).subquery()

    query = select(inner).order_by(inner.c.created_at.desc()).limit(max_entries)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.session_id,
            "agent_slug": row.agent_slug,
            "summary": row.summary_oneliner,
            "outcome": row.summary_outcome,
            "branch": row.summary_branch,
            "git_digest": row.summary_git_digest,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def query_from_session_columns(
    db: AsyncSession,
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
    staleness_cutoff: datetime,
    *,
    exclude_session_ids: set[str] | None = None,
) -> list[_SummaryDict]:
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
            "git_digest": row.summary_git_digest,
            "created_at": row.created_at,
        }
        for row in rows
    ]
