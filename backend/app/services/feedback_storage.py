"""CRUD operations for agent feedback system (issues, ideas, voting)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, cast, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import FeedbackItem, FeedbackVote

logger = logging.getLogger(__name__)

ACTIVE_FEEDBACK_STATUSES = ("open", "acknowledged")
TERMINAL_FEEDBACK_STATUSES = ("resolved", "wont_fix")
ARCHIVED_FEEDBACK_STATUS = "archived"


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
        conditions.append(text("search_vector @@ plainto_tsquery('english', :query)"))
    if component_id:
        conditions.append(FeedbackItem.component_id == component_id)
    if feedback_type:
        conditions.append(FeedbackItem.feedback_type == feedback_type)
    if status:
        conditions.append(_status_condition(status))
    if project_id:
        conditions.append(FeedbackItem.project_id == project_id)
    return conditions


def _status_condition(status: str):
    if status == "active":
        return FeedbackItem.status.in_(ACTIVE_FEEDBACK_STATUSES)
    return FeedbackItem.status == status


def _apply_feedback_item_filters(stmt, conditions: Iterable, *, query: str | None = None):
    for condition in conditions:
        stmt = stmt.where(condition)
    if query:
        stmt = stmt.params(query=query)
    return stmt


def _build_feedback_list_order(sort: str):
    sort_order = {
        "votes": (FeedbackItem.vote_count.desc(), FeedbackItem.created_at.desc()),
        "newest": (FeedbackItem.created_at.desc(),),
        "oldest": (FeedbackItem.created_at.asc(),),
    }
    return sort_order.get(sort, (FeedbackItem.vote_count.desc(),))


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
    stmt = _apply_feedback_item_filters(
        select(FeedbackItem), conditions, query=query
    ).order_by(*_build_feedback_list_order(sort))
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
    stmt = _apply_feedback_item_filters(
        select(func.count()).select_from(FeedbackItem), conditions, query=query
    )
    result = await db.execute(stmt)
    return result.scalar_one()


_DUPLICATE_CANDIDATES_SQL = text("""
    SELECT fi.*,
           CASE
               WHEN lower(fi.title) = lower(:title) THEN 1.0
               ELSE ts_rank(fi.search_vector, plainto_tsquery('english', :title))
           END AS rank
    FROM feedback_items fi
    WHERE fi.component_id = :component_id
      AND fi.feedback_type = :feedback_type
      AND fi.status IN ('open', 'acknowledged')
      AND (
          lower(fi.title) = lower(:title)
          OR fi.search_vector @@ plainto_tsquery('english', :title)
      )
    ORDER BY (fi.project_id = :project_id) DESC,
             (lower(fi.title) = lower(:title)) DESC,
             rank DESC
    LIMIT :limit
""")


async def _fetch_duplicate_rows(
    db: AsyncSession,
    *,
    component_id: str,
    feedback_type: str,
    project_id: str,
    title: str,
    limit: int,
) -> list:
    """Execute raw SQL and return mapping rows for duplicate candidates."""
    result = await db.execute(
        _DUPLICATE_CANDIDATES_SQL,
        {
            "component_id": component_id,
            "feedback_type": feedback_type,
            "project_id": project_id,
            "title": title,
            "limit": limit,
        },
    )
    return list(result.mappings().all())


async def _load_items_ordered(
    db: AsyncSession, ids: list[str]
) -> list[FeedbackItem]:
    """Load FeedbackItem ORM objects and return them in the given ID order."""
    if not ids:
        return []
    result = await db.execute(select(FeedbackItem).where(FeedbackItem.id.in_(ids)))
    items = {item.id: item for item in result.scalars().all()}
    return [items[id_] for id_ in ids if id_ in items]


async def find_duplicate_candidates(
    db: AsyncSession,
    *,
    component_id: str,
    feedback_type: str,
    project_id: str,
    title: str,
    limit: int = 5,
) -> list[FeedbackItem]:
    """Find existing open items that might be duplicates of a new submission.

    Uses PostgreSQL full-text search with ts_rank for relevance scoring.
    Only returns open/acknowledged items (not resolved/wont_fix). Feedback
    components are shared across projects, so duplicate matching is global for
    the same component/type while preferring same-project matches.
    """
    rows = await _fetch_duplicate_rows(
        db,
        component_id=component_id,
        feedback_type=feedback_type,
        project_id=project_id,
        title=title,
        limit=limit,
    )
    ids = [row["id"] for row in rows]
    return await _load_items_ordered(db, ids)


async def resolve_feedback_id(
    db: AsyncSession,
    item_id: str,
) -> str | None:
    """Resolve a full or prefix ID to a full UUID.

    Supports short prefix matching (like git short hashes):
    - Full UUID (36 chars): exact match
    - Short prefix (<36 chars): LIKE prefix match
    - Returns None if no match, raises ValueError if ambiguous
    """
    item_id = item_id.strip()
    if len(item_id) == 36:
        # Full UUID — check existence
        result = await db.execute(
            select(FeedbackItem.id).where(FeedbackItem.id == item_id)
        )
        row = result.scalar_one_or_none()
        return row if row else None

    # Prefix match
    result = await db.execute(
        select(FeedbackItem.id).where(
            cast(FeedbackItem.id, String).like(f"{item_id}%")
        ).limit(2)
    )
    matches = list(result.scalars().all())
    if len(matches) == 0:
        return None
    if len(matches) > 1:
        short_ids = [m[:12] for m in matches]
        raise ValueError(
            f"Ambiguous prefix '{item_id}' matches multiple items: {', '.join(short_ids)}..."
        )
    return matches[0]


async def get_feedback_item(
    db: AsyncSession,
    item_id: str,
) -> FeedbackItem | None:
    """Get a single feedback item by pre-resolved UUID.

    Accepts a full UUID string as resolved by the API layer (via resolve_feedback_id).
    Does not perform prefix resolution — callers must pass a full UUID.
    """
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

    # Flush the vote INSERT first — autoflush during the UPDATE below would
    # bypass the IntegrityError handler (the UPDATE triggers autoflush which
    # tries to insert the pending vote, hitting FK/unique constraints outside
    # the try/except).  Flushing here keeps the error path correct.
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None  # Duplicate vote or invalid session_id FK

    # Increment denormalized vote count only after vote is persisted
    await db.execute(
        update(FeedbackItem)
        .where(FeedbackItem.id == item_id)
        .values(vote_count=FeedbackItem.vote_count + 1)
    )
    return vote


async def update_feedback_status(
    db: AsyncSession,
    item_id: str,
    *,
    status: str | None = None,
    resolution_note: str | None = None,
    linked_task_id: str | None = None,
) -> FeedbackItem | None:
    """Update feedback item status, resolution note, or linked task.

    Accepts a pre-resolved UUID string. Resolution is the caller's responsibility.
    """
    result = await db.execute(
        select(FeedbackItem).where(FeedbackItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return None

    if status:
        item.status = status
        if status in TERMINAL_FEEDBACK_STATUSES:
            item.resolved_at = datetime.now(UTC)
        elif status in ACTIVE_FEEDBACK_STATUSES:
            item.resolved_at = None
    if resolution_note is not None:
        item.resolution_note = resolution_note
    if linked_task_id is not None:
        item.linked_task_id = linked_task_id

    await db.flush()
    return item


def _append_merged_text(existing: str | None, incoming: str | None) -> str | None:
    """Append unique merged text blocks while preserving readability."""
    cleaned_incoming = (incoming or "").strip()
    if not cleaned_incoming:
        return existing
    cleaned_existing = (existing or "").strip()
    if not cleaned_existing:
        return cleaned_incoming
    if cleaned_incoming in cleaned_existing:
        return cleaned_existing
    return f"{cleaned_existing}\n\nMerged duplicate note:\n{cleaned_incoming}"


async def _apply_vote_migration(
    db: AsyncSession,
    source_votes: list[FeedbackVote],
    target_item_id: str,
    target_votes_by_session: dict[str, FeedbackVote],
) -> None:
    """Migrate votes from source to target, merging comments for duplicate sessions."""
    for source_vote in source_votes:
        if source_vote.session_id and source_vote.session_id in target_votes_by_session:
            target_vote = target_votes_by_session[source_vote.session_id]
            target_vote.comment = _append_merged_text(target_vote.comment, source_vote.comment)
            await db.delete(source_vote)
        else:
            source_vote.feedback_item_id = target_item_id


async def merge_feedback_items(
    db: AsyncSession,
    *,
    source_item_id: str,
    target_item_id: str,
) -> FeedbackItem | None:
    """Merge a duplicate feedback item into a canonical item."""
    if source_item_id == target_item_id:
        raise ValueError("Cannot merge a feedback item into itself")

    result = await db.execute(
        select(FeedbackItem).where(FeedbackItem.id.in_([source_item_id, target_item_id]))
    )
    items = {item.id: item for item in result.scalars().all()}
    source = items.get(source_item_id)
    target = items.get(target_item_id)
    if source is None or target is None:
        return None

    source_votes = await get_feedback_votes(db, source_item_id)
    target_votes = await get_feedback_votes(db, target_item_id)
    target_votes_by_session = {
        vote.session_id: vote for vote in target_votes if vote.session_id is not None
    }
    await _apply_vote_migration(db, source_votes, target_item_id, target_votes_by_session)

    target.description = _append_merged_text(target.description, source.description)
    target.resolution_note = _append_merged_text(target.resolution_note, source.resolution_note)
    if target.linked_task_id is None and source.linked_task_id is not None:
        target.linked_task_id = source.linked_task_id
    if target.severity is None and source.severity is not None:
        target.severity = source.severity
    if target.status == ARCHIVED_FEEDBACK_STATUS and source.status in ACTIVE_FEEDBACK_STATUSES:
        target.status = source.status
    if target.created_by_session_id is None and source.created_by_session_id is not None:
        target.created_by_session_id = source.created_by_session_id

    await db.flush()

    vote_count_result = await db.execute(
        select(func.count()).select_from(FeedbackVote).where(FeedbackVote.feedback_item_id == target_item_id)
    )
    target.vote_count = vote_count_result.scalar_one()

    await db.execute(delete(FeedbackVote).where(FeedbackVote.feedback_item_id == source_item_id))
    await db.delete(source)
    await db.flush()
    return target


async def archive_stale_feedback_items(
    db: AsyncSession,
    *,
    older_than_days: int = 14,
) -> int:
    """Archive resolved or won't-fix items after a short grace period."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await db.execute(
        update(FeedbackItem)
        .where(
            FeedbackItem.status.in_(TERMINAL_FEEDBACK_STATUSES),
            FeedbackItem.resolved_at.is_not(None),
            FeedbackItem.resolved_at < cutoff,
        )
        .values(status=ARCHIVED_FEEDBACK_STATUS)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_old_archived_feedback_items(
    db: AsyncSession,
    *,
    older_than_days: int = 90,
    max_vote_count: int = 2,
) -> int:
    """Delete low-signal archived feedback after a long retention period."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await db.execute(
        select(FeedbackItem.id).where(
            FeedbackItem.status == ARCHIVED_FEEDBACK_STATUS,
            FeedbackItem.updated_at < cutoff,
            FeedbackItem.vote_count <= max_vote_count,
            FeedbackItem.linked_task_id.is_(None),
        )
    )
    item_ids = list(result.scalars().all())
    if not item_ids:
        return 0

    await db.execute(delete(FeedbackVote).where(FeedbackVote.feedback_item_id.in_(item_ids)))
    await db.execute(delete(FeedbackItem).where(FeedbackItem.id.in_(item_ids)))
    await db.flush()
    return len(item_ids)




async def delete_feedback_item(
    db: AsyncSession,
    item_id: str,
) -> bool:
    """Delete a feedback item and its votes. Returns True if deleted.

    Accepts a pre-resolved UUID string. Explicitly deletes related votes first
    to avoid ORM cascade issues with lazy="raise" on the votes relationship.
    """
    result = await db.execute(
        select(FeedbackItem).where(FeedbackItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return False
    # Explicitly delete votes to avoid ORM cascade with lazy="raise"
    await db.execute(delete(FeedbackVote).where(FeedbackVote.feedback_item_id == item_id))
    await db.delete(item)
    await db.flush()
    return True

def _build_summary_filter(project_id: str | None, days: int) -> tuple[str, dict[str, Any]]:
    """Build the WHERE clause fragment and params dict for summary queries."""
    base = "WHERE created_at >= NOW() - make_interval(days => :days)"
    params: dict[str, Any] = {"days": days}
    if project_id:
        base += " AND project_id = :project_id"
        params["project_id"] = project_id
    return base, params


async def _run_feedback_summary_queries(
    db: AsyncSession, base_filter: str, params: dict[str, Any]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Execute the three summary aggregation queries and return raw dicts."""
    counts_result = await db.execute(text(f"""
        SELECT feedback_type, status, COUNT(*) AS count
        FROM feedback_items
        {base_filter}
        GROUP BY feedback_type, status
        ORDER BY feedback_type, status
    """), params)
    counts = [dict(row) for row in counts_result.mappings().all()]

    top_result = await db.execute(text(f"""
        SELECT id, component_id, feedback_type, title, vote_count, status, created_at
        FROM feedback_items
        {base_filter} AND status IN ('open', 'acknowledged')
        ORDER BY vote_count DESC
        LIMIT 10
    """), params)
    top_items = [dict(row) for row in top_result.mappings().all()]

    component_result = await db.execute(text(f"""
        SELECT
            component_id,
            COUNT(*) FILTER (WHERE status IN ('open', 'acknowledged')) AS open_count,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
            COUNT(*) FILTER (WHERE status = 'wont_fix') AS wont_fix_count,
            COUNT(*) FILTER (WHERE status = 'archived') AS archived_count,
            COUNT(*) FILTER (WHERE feedback_type = 'friction') AS friction_count,
            COUNT(*) FILTER (WHERE feedback_type = 'idea') AS idea_count,
            COUNT(*) FILTER (WHERE feedback_type = 'praise') AS praise_count,
            SUM(vote_count) AS total_votes
        FROM feedback_items
        {base_filter}
        GROUP BY component_id
        ORDER BY open_count DESC
    """), params)
    by_component = [dict(row) for row in component_result.mappings().all()]

    return counts, top_items, by_component


async def get_feedback_summary(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Get aggregated feedback summary: counts by type/status, top items."""
    base_filter, params = _build_summary_filter(project_id, days)
    counts, top_items, by_component = await _run_feedback_summary_queries(db, base_filter, params)
    return {
        "total_items": sum(c["count"] for c in counts),
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
