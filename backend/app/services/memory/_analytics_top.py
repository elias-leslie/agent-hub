"""Top memory and tier-change queries for memory analytics."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db import async_session
from app.models.memory_unified import Memory
from app.services.memory_utility_score import utility_score_sql_expr

from .analytics_models import TopMemory
from .tier_operations import TIER_ACTOR

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


# Tier moves are memory revisions written by the optimizer (tier_operations.TIER_ACTOR); the tier a
# memory moved from is the tier on its previous revision. NULL when that revision was never stored.
_MOVES_CTE = """
WITH revs AS (
    SELECT memory_uuid, tier, lifecycle_score, created_at, changed_by,
           LAG(tier) OVER w AS prev_tier,
           LAG(lifecycle_score) OVER w AS prev_score
    FROM memory_revisions
    WINDOW w AS (PARTITION BY memory_uuid ORDER BY version, created_at)
), moves AS (
    SELECT memory_uuid, prev_tier, tier, prev_score, lifecycle_score, created_at,
           CASE WHEN prev_tier IS NULL THEN 'tier_move'
                WHEN tier < prev_tier THEN 'promotion'
                ELSE 'demotion' END AS change_type
    FROM revs
    WHERE (changed_by = :actor OR changed_by LIKE :actor_via)
      AND created_at >= :cutoff
      AND prev_tier IS DISTINCT FROM tier
)
"""

_TIER_CHANGES_SQL = (
    _MOVES_CTE + "SELECT change_type, COUNT(*) AS cnt, MAX(created_at) AS latest FROM moves GROUP BY change_type"
)

_TIER_RECENT_SQL = (
    _MOVES_CTE + "SELECT memory_uuid, prev_tier, tier, prev_score, lifecycle_score, change_type, created_at "
    "FROM moves ORDER BY created_at DESC LIMIT 20"
)


def _tier_name(tier: int | None) -> str | None:
    return None if tier is None else TIER_NAMES.get(tier, str(tier))


async def get_tier_changes_summary(
    days: int = 30,
    lookback_delta: timedelta | None = None,
) -> dict[str, object]:
    """Tier moves in the window, read from the optimizer's memory revisions.

    ``old_tier`` is None when the revision before the move was never stored, so the card
    can say the source tier is unknown rather than guess.
    """
    cutoff = datetime.now(UTC) - (lookback_delta or timedelta(days=days))
    params = {"cutoff": cutoff, "actor": TIER_ACTOR, "actor_via": f"{TIER_ACTOR} via %"}
    async with async_session() as session:
        summary_rows = (await session.execute(text(_TIER_CHANGES_SQL), params)).all()
        recent_rows = (await session.execute(text(_TIER_RECENT_SQL), params)).all()

    by_type = {
        row.change_type: {"count": row.cnt, "latest": row.latest.isoformat() if row.latest else None}
        for row in summary_rows
    }
    recent = [
        {
            "episode_uuid": r.memory_uuid,
            "old_tier": _tier_name(r.prev_tier),
            "new_tier": _tier_name(r.tier),
            "change_type": r.change_type,
            "lifecycle_score_before": r.prev_score,
            "lifecycle_score_after": r.lifecycle_score,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_rows
    ]
    return {"by_type": by_type, "recent": recent, "total": sum(r.cnt for r in summary_rows)}
