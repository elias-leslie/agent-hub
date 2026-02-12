"""
Truncation aggregation queries and logic.

Provides query building and data aggregation for truncation analytics.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, TruncationEvent

from .models import TruncationAggregation, TruncationFilters

logger = logging.getLogger(__name__)


def _apply_truncation_filters(query: Any, filters: TruncationFilters) -> Any:
    """Apply filters to a truncation aggregation query."""
    if filters.model:
        query = query.where(TruncationEvent.model.contains(filters.model))
    if filters.project_id:
        query = query.where(TruncationEvent.project_id == filters.project_id)
    if filters.start_date:
        query = query.where(TruncationEvent.created_at >= filters.start_date)
    if filters.end_date:
        query = query.where(TruncationEvent.created_at <= filters.end_date)
    return query


def _build_truncation_aggregation_select() -> list[Any]:
    """Build the standard SELECT clause for truncation aggregation."""
    return [
        func.count(TruncationEvent.id).label("count"),
        func.avg(TruncationEvent.output_tokens).label("avg_output"),
        func.avg(TruncationEvent.max_tokens_requested).label("avg_max"),
        func.sum(TruncationEvent.was_capped).label("capped"),
    ]


def _row_to_truncation_aggregation(row: Any, group_key: str = "total") -> TruncationAggregation:
    """Convert a query result row to TruncationAggregation."""
    return TruncationAggregation(
        group_key=str(getattr(row, "group_key", group_key)) if hasattr(row, "group_key") else group_key,
        truncation_count=int(getattr(row, "count", 0) or 0),
        avg_output_tokens=float(getattr(row, "avg_output", 0) or 0),
        avg_max_tokens=float(getattr(row, "avg_max", 0) or 0),
        capped_count=int(getattr(row, "capped", 0) or 0),
    )


async def aggregate_truncations_by_model(
    db: AsyncSession, filters: TruncationFilters
) -> list[TruncationAggregation]:
    """Aggregate truncations grouped by model."""
    query = select(
        TruncationEvent.model.label("group_key"),
        *_build_truncation_aggregation_select(),
    ).group_by(TruncationEvent.model)
    query = _apply_truncation_filters(query, filters)
    result = await db.execute(query)
    return [_row_to_truncation_aggregation(row) for row in result.all()]


async def aggregate_truncations_by_time(
    db: AsyncSession, filters: TruncationFilters, period: str
) -> list[TruncationAggregation]:
    """Aggregate truncations grouped by time period (day/week/month)."""
    date_trunc = func.date_trunc(period, TruncationEvent.created_at)
    query = (
        select(
            date_trunc.label("group_key"),
            *_build_truncation_aggregation_select(),
        )
        .group_by(date_trunc)
        .order_by(date_trunc)
    )
    query = _apply_truncation_filters(query, filters)
    result = await db.execute(query)
    return [_row_to_truncation_aggregation(row) for row in result.all()]


async def aggregate_truncations_total(
    db: AsyncSession, filters: TruncationFilters
) -> list[TruncationAggregation]:
    """Get total truncation aggregation (no grouping)."""
    query = select(*_build_truncation_aggregation_select())
    query = _apply_truncation_filters(query, filters)
    result = await db.execute(query)
    row = result.one()
    if getattr(row, "count", None):
        return [_row_to_truncation_aggregation(row)]
    return []


async def get_truncation_rate(
    db: AsyncSession, total_truncations: int, filters: TruncationFilters
) -> float:
    """Calculate truncation rate as percentage of total requests."""
    count_query = select(func.count(CostLog.id))
    if filters.start_date:
        count_query = count_query.where(CostLog.created_at >= filters.start_date)
    if filters.end_date:
        count_query = count_query.where(CostLog.created_at <= filters.end_date)
    if filters.model:
        count_query = count_query.where(CostLog.model.contains(filters.model))

    count_result = await db.execute(count_query)
    total_requests = count_result.scalar() or 0
    return (total_truncations / total_requests * 100) if total_requests > 0 else 0.0


async def get_recent_truncation_events(
    db: AsyncSession, filters: TruncationFilters, limit: int = 10
) -> list[dict[str, Any]]:
    """Get recent truncation events for debugging."""
    query = (
        select(TruncationEvent).order_by(TruncationEvent.created_at.desc()).limit(limit)
    )
    if filters.model:
        query = query.where(TruncationEvent.model.contains(filters.model))
    if filters.project_id:
        query = query.where(TruncationEvent.project_id == filters.project_id)

    result = await db.execute(query)
    events = []
    for event in result.scalars().all():
        events.append(
            {
                "id": event.id,
                "model": event.model,
                "endpoint": event.endpoint,
                "output_tokens": event.output_tokens,
                "max_tokens_requested": event.max_tokens_requested,
                "model_limit": event.model_limit,
                "was_capped": bool(event.was_capped),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        )
    return events
