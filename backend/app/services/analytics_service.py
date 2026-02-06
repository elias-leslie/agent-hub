"""
Analytics service for cost and truncation aggregation.

Provides query building and data aggregation for analytics endpoints.
"""

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session, TruncationEvent

logger = logging.getLogger(__name__)


class CostAggregation(BaseModel):
    """Aggregated cost data for a group."""

    group_key: str = Field(..., description="Group identifier")
    total_tokens: int = Field(..., description="Total tokens (input + output)")
    input_tokens: int = Field(..., description="Total input tokens")
    output_tokens: int = Field(..., description="Total output tokens")
    total_cost_usd: float = Field(..., description="Total estimated cost in USD")
    request_count: int = Field(..., description="Number of requests")


class TruncationAggregation(BaseModel):
    """Aggregated truncation data for a group."""

    group_key: str = Field(..., description="Group identifier (model, day, etc.)")
    truncation_count: int = Field(..., description="Number of truncation events")
    avg_output_tokens: float = Field(..., description="Average output tokens when truncated")
    avg_max_tokens: float = Field(..., description="Average max_tokens requested")
    capped_count: int = Field(..., description="Events where max_tokens was capped to model limit")


class CostFilters(BaseModel):
    """Filters for cost aggregation queries."""

    project_id: str | None = None
    model: str | None = None
    agent_slug: str | None = None
    session_type: str | None = None
    external_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class TruncationFilters(BaseModel):
    """Filters for truncation aggregation queries."""

    model: str | None = None
    project_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


def _apply_cost_filters(query: Any, filters: CostFilters, needs_session_join: bool = False) -> Any:
    """Apply filters to a cost aggregation query."""
    if filters.project_id:
        if not needs_session_join:
            query = query.join(Session, CostLog.session_id == Session.id)
        query = query.where(Session.project_id == filters.project_id)
    if filters.model:
        query = query.where(CostLog.model.contains(filters.model))
    if filters.agent_slug:
        if not needs_session_join and not filters.project_id:
            query = query.join(Session, CostLog.session_id == Session.id)
        query = query.where(Session.agent_slug == filters.agent_slug)
    if filters.session_type:
        if not needs_session_join and not filters.project_id and not filters.agent_slug:
            query = query.join(Session, CostLog.session_id == Session.id)
        query = query.where(Session.session_type == filters.session_type)
    if filters.external_id:
        if (
            not needs_session_join
            and not filters.project_id
            and not filters.agent_slug
            and not filters.session_type
        ):
            query = query.join(Session, CostLog.session_id == Session.id)
        query = query.where(Session.external_id == filters.external_id)
    if filters.start_date:
        query = query.where(CostLog.created_at >= filters.start_date)
    if filters.end_date:
        query = query.where(CostLog.created_at <= filters.end_date)
    return query


def _build_cost_aggregation_select() -> list[Any]:
    """Build the standard SELECT clause for cost aggregation."""
    return [
        func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
        func.sum(CostLog.input_tokens).label("input_tokens"),
        func.sum(CostLog.output_tokens).label("output_tokens"),
        func.sum(CostLog.cost_usd).label("total_cost"),
        func.count(CostLog.id).label("request_count"),
    ]


def _row_to_cost_aggregation(row: Any, default_key: str = "unknown") -> CostAggregation:
    """Convert a query result row to CostAggregation."""
    return CostAggregation(
        group_key=str(getattr(row, "group_key", default_key)) if hasattr(row, "group_key") else default_key,
        total_tokens=int(getattr(row, "total_tokens", 0) or 0),
        input_tokens=int(getattr(row, "input_tokens", 0) or 0),
        output_tokens=int(getattr(row, "output_tokens", 0) or 0),
        total_cost_usd=float(getattr(row, "total_cost", 0.0) or 0.0),
        request_count=int(getattr(row, "request_count", 0) or 0),
    )


async def aggregate_costs_by_project(
    db: AsyncSession, filters: CostFilters
) -> list[CostAggregation]:
    """Aggregate costs grouped by project."""
    query = (
        select(
            Session.project_id.label("group_key"),
            *_build_cost_aggregation_select(),
        )
        .join(Session, CostLog.session_id == Session.id)
        .group_by(Session.project_id)
    )
    query = _apply_cost_filters(query, filters, needs_session_join=True)
    result = await db.execute(query)
    return [_row_to_cost_aggregation(row) for row in result.all()]


async def aggregate_costs_by_agent(
    db: AsyncSession, filters: CostFilters
) -> list[CostAggregation]:
    """Aggregate costs grouped by agent slug."""
    query = (
        select(
            Session.agent_slug.label("group_key"),
            *_build_cost_aggregation_select(),
        )
        .join(Session, CostLog.session_id == Session.id)
        .group_by(Session.agent_slug)
    )
    query = _apply_cost_filters(query, filters, needs_session_join=True)
    result = await db.execute(query)
    return [_row_to_cost_aggregation(row, default_key="unspecified") for row in result.all()]


async def aggregate_costs_by_session_type(
    db: AsyncSession, filters: CostFilters
) -> list[CostAggregation]:
    """Aggregate costs grouped by session type."""
    query = (
        select(
            Session.session_type.label("group_key"),
            *_build_cost_aggregation_select(),
        )
        .join(Session, CostLog.session_id == Session.id)
        .group_by(Session.session_type)
    )
    query = _apply_cost_filters(query, filters, needs_session_join=True)
    result = await db.execute(query)
    return [
        CostAggregation(
            group_key=str(row.group_key) if row.group_key else "completion",
            total_tokens=int(row.total_tokens or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            total_cost_usd=float(row.total_cost or 0.0),
            request_count=int(row.request_count or 0),
        )
        for row in result.all()
    ]


async def aggregate_costs_by_external_id(
    db: AsyncSession, filters: CostFilters
) -> list[CostAggregation]:
    """Aggregate costs grouped by external ID."""
    query = (
        select(
            Session.external_id.label("group_key"),
            *_build_cost_aggregation_select(),
        )
        .join(Session, CostLog.session_id == Session.id)
        .group_by(Session.external_id)
    )
    query = _apply_cost_filters(query, filters, needs_session_join=True)
    result = await db.execute(query)
    return [_row_to_cost_aggregation(row, default_key="unspecified") for row in result.all()]


async def aggregate_costs_by_model(
    db: AsyncSession, filters: CostFilters
) -> list[CostAggregation]:
    """Aggregate costs grouped by model."""
    query = select(
        CostLog.model.label("group_key"),
        *_build_cost_aggregation_select(),
    ).group_by(CostLog.model)
    query = _apply_cost_filters(query, filters)
    result = await db.execute(query)
    return [_row_to_cost_aggregation(row) for row in result.all()]


async def aggregate_costs_by_time(
    db: AsyncSession, filters: CostFilters, period: str
) -> list[CostAggregation]:
    """Aggregate costs grouped by time period (day/week/month)."""
    date_trunc = func.date_trunc(period, CostLog.created_at)
    query = (
        select(
            date_trunc.label("group_key"),
            *_build_cost_aggregation_select(),
        )
        .group_by(date_trunc)
        .order_by(date_trunc)
    )
    query = _apply_cost_filters(query, filters)
    result = await db.execute(query)
    return [_row_to_cost_aggregation(row) for row in result.all()]


async def aggregate_costs_total(db: AsyncSession, filters: CostFilters) -> list[CostAggregation]:
    """Get total cost aggregation (no grouping)."""
    query = select(*_build_cost_aggregation_select())
    query = _apply_cost_filters(query, filters)
    result = await db.execute(query)
    row = result.one()
    if row.total_tokens:
        return [_row_to_cost_aggregation(row, default_key="total")]
    return []


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
