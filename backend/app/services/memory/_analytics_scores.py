"""Score and usage metric queries for memory analytics."""

from datetime import datetime

from sqlalchemy import func, select

from app.db import async_session
from app.models.memory import UsageStatLog
from app.models.memory_unified import Memory
from app.services.memory_utility_score import utility_score_sql_expr

from .analytics_models import DailyTrend
from .repository import TIER_REVERSE

_TIER_NAMES = TIER_REVERSE


async def get_usage_aggregates(group_id: str | None = None) -> dict[str, int]:
    """Get aggregate usage metrics for active memories."""
    stmt = select(
        func.coalesce(func.sum(Memory.loaded_count), 0).label("loaded"),
        func.coalesce(func.sum(Memory.referenced_count), 0).label("referenced"),
        func.coalesce(func.sum(Memory.helpful_count), 0).label("helpful"),
        func.coalesce(func.sum(Memory.harmful_count), 0).label("harmful"),
    ).where(Memory.status == "active")
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    success_stmt = select(func.coalesce(func.sum(UsageStatLog.value), 0)).where(
        UsageStatLog.metric_type == "success"
    )

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
    """Get daily count of memory creation since cutoff date."""
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


async def get_avg_utility_score(group_id: str | None = None) -> float:
    """Get average normalized utility score for active memories."""
    utility_expr = utility_score_sql_expr(Memory.loaded_count, Memory.referenced_count)
    stmt = select(func.avg(utility_expr).label("avg_score")).where(
        Memory.status == "active",
        Memory.loaded_count > 0,
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        result = (await session.execute(stmt)).scalar()

    return round(float(result), 4) if result else 0.0


async def get_avg_lifecycle_score(group_id: str | None = None) -> float:
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


async def get_lifecycle_by_tier(group_id: str | None = None) -> dict[str, float]:
    """Get average lifecycle score per tier for active memories."""
    stmt = (
        select(Memory.tier, func.avg(Memory.lifecycle_score).label("avg_score"))
        .where(Memory.status == "active", Memory.lifecycle_score.isnot(None))
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
