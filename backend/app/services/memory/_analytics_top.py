"""Top memory and tier-change queries for memory analytics."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db import async_session
from app.models.memory_unified import Memory
from app.services.memory_utility_score import utility_score_sql_expr

from .analytics_models import TopMemory

ALLOWED_SORT_FIELDS = {"utility_score", "referenced_count", "loaded_count", "helpful_count", "lifecycle_score"}
TIER_NAMES = {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}

_SORT_EXPR_MAP = {
    "referenced_count": lambda: Memory.referenced_count,
    "loaded_count": lambda: Memory.loaded_count,
    "helpful_count": lambda: Memory.helpful_count,
    "lifecycle_score": lambda: Memory.lifecycle_score,
}


def _build_sort_expr(sort_by: str):
    """Return the SQLAlchemy sort expression for the given field name."""
    if sort_by in _SORT_EXPR_MAP:
        return _SORT_EXPR_MAP[sort_by]()
    return utility_score_sql_expr(Memory.loaded_count, Memory.referenced_count)


def _build_order(sort_by: str, sort_expr):
    """Return ordered expression (nulls last for lifecycle_score)."""
    if sort_by == "lifecycle_score":
        return sort_expr.desc().nulls_last()
    return sort_expr.desc()


async def get_top_memories_query(
    group_id: str | None = None,
    sort_by: str = "utility_score",
    limit: int = 8,
) -> list[TopMemory]:
    """Get top performing memories sorted by specified field."""
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "utility_score"

    sort_expr = _build_sort_expr(sort_by)
    order = _build_order(sort_by, sort_expr)
    utility_expr = utility_score_sql_expr(Memory.loaded_count, Memory.referenced_count)

    stmt = (
        select(
            Memory.id,
            Memory.content,
            Memory.tier,
            Memory.loaded_count,
            Memory.referenced_count,
            Memory.lifecycle_score,
            utility_expr.label("utility_score"),
        )
        .where(Memory.status == "active")
        .order_by(order)
        .limit(limit)
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    return [
        TopMemory(
            uuid=str(row.id),
            content=(row.content or "")[:120],
            injection_tier=TIER_NAMES.get(row.tier, "reference"),
            utility_score=round(float(row.utility_score or 0), 4),
            loaded_count=row.loaded_count,
            referenced_count=row.referenced_count,
            lifecycle_score=round(row.lifecycle_score, 4) if row.lifecycle_score is not None else None,
        )
        for row in rows
    ]


_TIER_CHANGES_SQL = (
    "SELECT change_type, COUNT(*) as cnt, MAX(created_at) as latest "
    "FROM tier_change_log "
    "WHERE created_at >= :cutoff "
    "GROUP BY change_type"
)

_TIER_RECENT_SQL = (
    "SELECT episode_uuid, old_tier, new_tier, change_type, "
    "lifecycle_score_before, lifecycle_score_after, created_at "
    "FROM tier_change_log "
    "WHERE created_at >= :cutoff "
    "ORDER BY created_at DESC LIMIT 20"
)


async def get_tier_changes_summary(
    days: int = 30,
    lookback_delta: timedelta | None = None,
) -> dict[str, object]:
    """Get tier change activity from tier_change_log."""
    cutoff = datetime.now(UTC) - (lookback_delta or timedelta(days=days))
    params = {"cutoff": cutoff}
    async with async_session() as session:
        summary_rows = (await session.execute(text(_TIER_CHANGES_SQL), params)).all()
        recent_rows = (await session.execute(text(_TIER_RECENT_SQL), params)).all()

    by_type = {
        row.change_type: {"count": row.cnt, "latest": row.latest.isoformat() if row.latest else None}
        for row in summary_rows
    }
    recent = [
        {
            "episode_uuid": r.episode_uuid,
            "old_tier": r.old_tier,
            "new_tier": r.new_tier,
            "change_type": r.change_type,
            "lifecycle_score_before": r.lifecycle_score_before,
            "lifecycle_score_after": r.lifecycle_score_after,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_rows
    ]
    return {"by_type": by_type, "recent": recent, "total": sum(r.cnt for r in summary_rows)}
