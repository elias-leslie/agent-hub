"""
Cost aggregation queries and logic.

Provides query building and data aggregation for cost analytics.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session

from .models import CostAggregation, CostFilters

logger = logging.getLogger(__name__)


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
