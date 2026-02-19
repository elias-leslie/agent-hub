"""CRUD operations for agent feedback system (issues, ideas, voting)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import FeedbackItem, FeedbackVote

logger = logging.getLogger(__name__)


async def create_feedback_item(
    db: AsyncSession,
    *,
    component_id: str,
    feedback_type: str,
    title: str,
    project_id: str,
    description: str | None = None,
    severity: str | None = None,
    session_id: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
    session_type: str | None = None,
) -> FeedbackItem:
    """Create a new feedback item."""
    item = FeedbackItem(
        component_id=component_id,
        feedback_type=feedback_type,
        title=title,
        description=description,
        severity=severity,
        project_id=project_id,
        created_by_session_id=session_id,
        agent_slug=agent_slug,
        model_used=model_used,
        session_type=session_type,
    )
    db.add(item)
    await db.flush()
    return item


def _build_search_filters(
    query: str | None = None,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
) -> list:
    """Build shared filter conditions for search queries."""
    conditions = []
    if query:
        conditions.append(
            text("search_vector @@ plainto_tsquery('english', :query)")
        )
    if component_id:
        conditions.append(FeedbackItem.component_id == component_id)
    if feedback_type:
        conditions.append(FeedbackItem.feedback_type == feedback_type)
    if status:
        conditions.append(FeedbackItem.status == status)
    if project_id:
        conditions.append(FeedbackItem.project_id == project_id)
    return conditions


async def search_feedback_items(
    db: AsyncSession,
    *,
    query: str | None = None,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 50,
    offset: int = 0,
) -> list[FeedbackItem]:
    """Search/list feedback items with filters."""
    conditions = _build_search_filters(query, component_id, feedback_type, status, project_id)
    stmt = select(FeedbackItem)
    for cond in conditions:
        stmt = stmt.where(cond)
    if query:
        stmt = stmt.params(query=query)

    if sort == "votes":
        stmt = stmt.order_by(FeedbackItem.vote_count.desc(), FeedbackItem.created_at.desc())
    elif sort == "newest":
        stmt = stmt.order_by(FeedbackItem.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(FeedbackItem.created_at.asc())
    else:
        stmt = stmt.order_by(FeedbackItem.vote_count.desc())

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_feedback_items(
    db: AsyncSession,
    *,
    query: str | None = None,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
) -> int:
    """Count feedback items matching filters (for pagination total)."""
    conditions = _build_search_filters(query, component_id, feedback_type, status, project_id)
    stmt = select(func.count()).select_from(FeedbackItem)
    for cond in conditions:
        stmt = stmt.where(cond)
    if query:
        stmt = stmt.params(query=query)
    result = await db.execute(stmt)
    return result.scalar_one()


async def find_duplicate_candidates(
    db: AsyncSession,
    *,
    component_id: str,
    title: str,
    limit: int = 5,
) -> list[FeedbackItem]:
    """Find existing open items that might be duplicates of a new submission.

    Uses PostgreSQL full-text search with ts_rank for relevance scoring.
    Only returns open/acknowledged items (not resolved/wont_fix).
    """
    stmt = text("""
        SELECT fi.*,
               ts_rank(fi.search_vector, plainto_tsquery('english', :title)) AS rank
        FROM feedback_items fi
        WHERE fi.component_id = :component_id
        AND fi.status IN ('open', 'acknowledged')
        AND fi.search_vector @@ plainto_tsquery('english', :title)
        ORDER BY rank DESC
        LIMIT :limit
    """)
    result = await db.execute(
        stmt, {"component_id": component_id, "title": title, "limit": limit}
    )
    rows = result.mappings().all()
    if not rows:
        return []

    # Load as ORM objects
    ids = [row["id"] for row in rows]
    orm_result = await db.execute(
        select(FeedbackItem).where(FeedbackItem.id.in_(ids))
    )
    items = {item.id: item for item in orm_result.scalars().all()}
    # Preserve rank ordering
    return [items[id_] for id_ in ids if id_ in items]


async def get_feedback_item(
    db: AsyncSession,
    item_id: str,
) -> FeedbackItem | None:
    """Get a single feedback item by ID."""
    result = await db.execute(
        select(FeedbackItem).where(FeedbackItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def get_feedback_votes(
    db: AsyncSession,
    item_id: str,
) -> list[FeedbackVote]:
    """Get all votes for a feedback item."""
    result = await db.execute(
        select(FeedbackVote)
        .where(FeedbackVote.feedback_item_id == item_id)
        .order_by(FeedbackVote.created_at.desc())
    )
    return list(result.scalars().all())


async def vote_on_item(
    db: AsyncSession,
    *,
    item_id: str,
    session_id: str,
    comment: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
) -> FeedbackVote | None:
    """Vote on a feedback item. Returns None if already voted (idempotent).

    Increments the denormalized vote_count on the parent item.
    Handles concurrent duplicate votes via IntegrityError catch.
    """
    # Check for existing vote (unique constraint: feedback_item_id + session_id)
    existing = await db.execute(
        select(FeedbackVote).where(
            FeedbackVote.feedback_item_id == item_id,
            FeedbackVote.session_id == session_id,
        )
    )
    if existing.scalar_one_or_none():
        return None  # Already voted

    vote = FeedbackVote(
        feedback_item_id=item_id,
        session_id=session_id,
        comment=comment,
        agent_slug=agent_slug,
        model_used=model_used,
    )
    db.add(vote)

    # Increment denormalized vote count
    await db.execute(
        update(FeedbackItem)
        .where(FeedbackItem.id == item_id)
        .values(vote_count=FeedbackItem.vote_count + 1)
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None  # Concurrent duplicate vote
    return vote


async def update_feedback_status(
    db: AsyncSession,
    item_id: str,
    *,
    status: str | None = None,
    resolution_note: str | None = None,
    linked_task_id: str | None = None,
) -> FeedbackItem | None:
    """Update feedback item status, resolution note, or linked task."""
    item = await get_feedback_item(db, item_id)
    if not item:
        return None

    if status:
        item.status = status
        if status == "resolved":
            item.resolved_at = datetime.now(UTC)
    if resolution_note is not None:
        item.resolution_note = resolution_note
    if linked_task_id is not None:
        item.linked_task_id = linked_task_id

    await db.flush()
    return item




async def delete_feedback_item(
    db: AsyncSession,
    item_id: str,
) -> bool:
    """Delete a feedback item and its votes. Returns True if deleted."""
    item = await get_feedback_item(db, item_id)
    if not item:
        return False
    await db.delete(item)
    await db.flush()
    return True

async def get_feedback_summary(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Get aggregated feedback summary: counts by type/status, top items."""
    base_filter = "WHERE created_at >= NOW() - make_interval(days => :days)"
    params: dict[str, Any] = {"days": days}
    if project_id:
        base_filter += " AND project_id = :project_id"
        params["project_id"] = project_id

    # Counts by type and status
    counts_query = text(f"""
        SELECT
            feedback_type,
            status,
            COUNT(*) AS count
        FROM feedback_items
        {base_filter}
        GROUP BY feedback_type, status
        ORDER BY feedback_type, status
    """)
    counts_result = await db.execute(counts_query, params)
    counts = [dict(row) for row in counts_result.mappings().all()]

    # Top unresolved by votes
    top_query = text(f"""
        SELECT id, component_id, feedback_type, title, vote_count, status, created_at
        FROM feedback_items
        {base_filter} AND status IN ('open', 'acknowledged')
        ORDER BY vote_count DESC
        LIMIT 10
    """)
    top_result = await db.execute(top_query, params)
    top_items = [dict(row) for row in top_result.mappings().all()]

    # Per-component breakdown
    component_query = text(f"""
        SELECT
            component_id,
            COUNT(*) FILTER (WHERE status IN ('open', 'acknowledged')) AS open_count,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
            COUNT(*) FILTER (WHERE feedback_type = 'friction') AS friction_count,
            COUNT(*) FILTER (WHERE feedback_type = 'idea') AS idea_count,
            COUNT(*) FILTER (WHERE feedback_type = 'praise') AS praise_count,
            SUM(vote_count) AS total_votes
        FROM feedback_items
        {base_filter}
        GROUP BY component_id
        ORDER BY open_count DESC
    """)
    component_result = await db.execute(component_query, params)
    by_component = [dict(row) for row in component_result.mappings().all()]

    total = sum(c["count"] for c in counts)

    return {
        "total_items": total,
        "counts_by_type_status": counts,
        "top_unresolved": top_items,
        "by_component": by_component,
    }


async def get_component_feedback(
    db: AsyncSession,
    component_id: str,
    *,
    days: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    """Get feedback for a specific component."""
    # Filter items by the same time window used for stats
    cutoff = datetime.now(UTC) - timedelta(days=days)
    items_stmt = select(FeedbackItem).where(
        FeedbackItem.component_id == component_id,
        FeedbackItem.created_at >= cutoff,
    ).order_by(FeedbackItem.vote_count.desc()).limit(limit)
    items_result = await db.execute(items_stmt)
    items = list(items_result.scalars().all())

    # Stats for this component
    stats_query = text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status IN ('open', 'acknowledged')) AS open_count,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
            COUNT(*) FILTER (WHERE feedback_type = 'friction') AS friction_count,
            COUNT(*) FILTER (WHERE feedback_type = 'idea') AS idea_count,
            COUNT(*) FILTER (WHERE feedback_type = 'improvement') AS improvement_count,
            COUNT(*) FILTER (WHERE feedback_type = 'praise') AS praise_count
        FROM feedback_items
        WHERE component_id = :component_id
        AND created_at >= NOW() - make_interval(days => :days)
    """)
    result = await db.execute(stats_query, {"component_id": component_id, "days": days})
    stats = dict(result.mappings().one())

    return {
        "component_id": component_id,
        "stats": stats,
        "items": items,
    }
