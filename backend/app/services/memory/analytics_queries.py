"""Database query functions for memory analytics."""

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select, text

from app.db import async_session
from app.models.memory import UsageStatLog
from app.models.memory_unified import Memory

from .analytics_models import DailyTrend, ScopeDistribution, TierDistribution, TopMemory
from .repository import TIER_REVERSE

logger = logging.getLogger(__name__)

ALLOWED_SORT_FIELDS = {"utility_score", "referenced_count", "loaded_count", "helpful_count", "lifecycle_score"}

# Map tier numbers to names for distribution reporting
_TIER_NAMES = TIER_REVERSE  # {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}


async def get_tier_distribution(
    group_id: str | None = None,
) -> list[TierDistribution]:
    """Get distribution of memories across injection tiers."""
    stmt = (
        select(Memory.tier, func.count(Memory.id).label("cnt"))
        .where(Memory.status == "active")
        .group_by(Memory.tier)
        .order_by(func.count(Memory.id).desc())
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    total = sum(cnt for _, cnt in rows)
    return [
        TierDistribution(
            tier=_TIER_NAMES.get(tier_num, "unknown"),
            count=cnt,
            percentage=round(cnt / total * 100, 1) if total > 0 else 0.0,
        )
        for tier_num, cnt in rows
    ]


async def get_scope_distribution(
    group_id: str | None = None,
) -> list[ScopeDistribution]:
    """Get distribution of memories across scopes (global/project)."""
    stmt = (
        select(Memory.scope, func.count(Memory.id).label("cnt"))
        .where(Memory.status == "active")
        .group_by(Memory.scope)
        .order_by(func.count(Memory.id).desc())
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    # Aggregate into broad categories (global vs project)
    scope_counts: dict[str, int] = defaultdict(int)
    for scope_val, cnt in rows:
        if scope_val and scope_val.startswith("project:"):
            scope_counts["project"] += cnt
        else:
            scope_counts["global"] += cnt

    total = sum(scope_counts.values())
    return [
        ScopeDistribution(
            scope=scope,
            count=count,
            percentage=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
    ]


async def get_usage_aggregates(
    group_id: str | None = None,
) -> dict[str, int]:
    """Get aggregate usage metrics for memories."""
    stmt = select(
        func.coalesce(func.sum(Memory.loaded_count), 0).label("loaded"),
        func.coalesce(func.sum(Memory.referenced_count), 0).label("referenced"),
        func.coalesce(func.sum(Memory.helpful_count), 0).label("helpful"),
        func.coalesce(func.sum(Memory.harmful_count), 0).label("harmful"),
    ).where(Memory.status == "active")

    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    success_stmt = select(
        func.coalesce(func.sum(UsageStatLog.value), 0)
    ).where(UsageStatLog.metric_type == "success")

    async with async_session() as session:
        row = (await session.execute(stmt)).one_or_none()
        success_total = (await session.execute(success_stmt)).scalar() or 0

    if not row:
        return {"loaded": 0, "referenced": 0, "helpful": 0, "harmful": 0, "success": int(success_total)}

    return {
        "loaded": int(row.loaded),
        "referenced": int(row.referenced),
        "helpful": int(row.helpful),
        "harmful": int(row.harmful),
        "success": int(success_total),
    }


async def get_daily_trend(
    group_id: str | None = None,
    cutoff: datetime | None = None,
) -> list[DailyTrend]:
    """Get daily trend of memory creation since cutoff date."""
    day_expr = func.date(Memory.created_at)
    stmt = (
        select(day_expr.label("day"), func.count(Memory.id).label("cnt"))
        .where(Memory.status == "active")
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )

    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)
    if cutoff:
        stmt = stmt.where(Memory.created_at >= cutoff)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    return [DailyTrend(date=str(day), count=cnt) for day, cnt in rows]


async def get_avg_utility_score(
    group_id: str | None = None,
) -> float:
    """Get average utility score of memories with usage.

    utility_score = referenced_count / (loaded_count + 1), computed in SQL.
    """
    utility_expr = Memory.referenced_count * 1.0 / (Memory.loaded_count + 1)
    stmt = select(func.avg(utility_expr).label("avg_score")).where(
        Memory.status == "active",
        Memory.loaded_count > 0,
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        result = (await session.execute(stmt)).scalar()

    return round(float(result), 4) if result else 0.0


async def get_avg_lifecycle_score(
    group_id: str | None = None,
) -> float:
    """Get average lifecycle score of active memories that have been scored."""
    stmt = select(func.avg(Memory.lifecycle_score).label("avg_score")).where(
        Memory.status == "active",
        Memory.lifecycle_score.isnot(None),
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        result = (await session.execute(stmt)).scalar()

    return round(float(result), 4) if result else 0.0


async def get_lifecycle_by_tier(
    group_id: str | None = None,
) -> dict[str, float]:
    """Get average lifecycle score per tier for active memories."""
    stmt = (
        select(
            Memory.tier,
            func.avg(Memory.lifecycle_score).label("avg_score"),
        )
        .where(
            Memory.status == "active",
            Memory.lifecycle_score.isnot(None),
        )
        .group_by(Memory.tier)
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    return {
        _TIER_NAMES.get(tier_num, "unknown"): round(float(avg), 4)
        for tier_num, avg in rows
        if avg is not None
    }


async def get_tier_changes_summary(
    days: int = 30,
) -> dict:
    """Get tier change activity from tier_change_log."""
    async with async_session() as session:
        # Aggregate counts by change_type
        summary_rows = (
            await session.execute(
                text(
                    "SELECT change_type, COUNT(*) as cnt, MAX(created_at) as latest "
                    "FROM tier_change_log "
                    "WHERE created_at >= NOW() - INTERVAL :days "
                    "GROUP BY change_type"
                ),
                {"days": f"{days} days"},
            )
        ).all()

        # Recent entries with lifecycle scores
        recent_rows = (
            await session.execute(
                text(
                    "SELECT episode_uuid, old_tier, new_tier, change_type, "
                    "lifecycle_score_before, lifecycle_score_after, created_at "
                    "FROM tier_change_log "
                    "WHERE created_at >= NOW() - INTERVAL :days "
                    "ORDER BY created_at DESC LIMIT 20"
                ),
                {"days": f"{days} days"},
            )
        ).all()

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


async def get_top_memories_query(
    group_id: str | None = None,
    sort_by: str = "utility_score",
    limit: int = 8,
) -> list[TopMemory]:
    """Get top performing memories sorted by specified field."""
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "utility_score"

    # Build the sort expression
    if sort_by == "utility_score":
        sort_expr = (Memory.referenced_count * 1.0 / (Memory.loaded_count + 1))
    elif sort_by == "referenced_count":
        sort_expr = Memory.referenced_count
    elif sort_by == "loaded_count":
        sort_expr = Memory.loaded_count
    elif sort_by == "helpful_count":
        sort_expr = Memory.helpful_count
    elif sort_by == "lifecycle_score":
        sort_expr = Memory.lifecycle_score
    else:
        sort_expr = Memory.referenced_count

    order = sort_expr.desc().nulls_last() if sort_by == "lifecycle_score" else sort_expr.desc()

    stmt = (
        select(Memory)
        .where(Memory.status == "active")
        .order_by(order)
        .limit(limit)
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = list((await session.execute(stmt)).scalars().all())

    return [
        TopMemory(
            uuid=str(mem.id),
            content=(mem.content or "")[:120],
            injection_tier=mem.injection_tier,
            utility_score=round(mem.utility_score, 4),
            loaded_count=mem.loaded_count,
            referenced_count=mem.referenced_count,
            lifecycle_score=round(mem.lifecycle_score, 4) if mem.lifecycle_score is not None else None,
        )
        for mem in rows
    ]
