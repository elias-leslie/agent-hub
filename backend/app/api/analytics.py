"""
Analytics API endpoints for cost aggregation.

GET /analytics/costs - Aggregate cost data with grouping options.
"""

import logging
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CostLog, Session, TruncationEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


class GroupBy(str, Enum):
    """Grouping options for cost aggregation."""

    project = "project"
    model = "model"
    agent_slug = "agent_slug"
    session_type = "session_type"
    external_id = "external_id"
    day = "day"
    week = "week"
    month = "month"
    none = "none"


class CostAggregation(BaseModel):
    """Aggregated cost data for a group."""

    group_key: str = Field(..., description="Group identifier")
    total_tokens: int = Field(..., description="Total tokens (input + output)")
    input_tokens: int = Field(..., description="Total input tokens")
    output_tokens: int = Field(..., description="Total output tokens")
    total_cost_usd: float = Field(..., description="Total estimated cost in USD")
    request_count: int = Field(..., description="Number of requests")


class CostAggregationResponse(BaseModel):
    """Response for cost aggregation endpoint."""

    aggregations: list[CostAggregation] = Field(..., description="Aggregated cost data")
    total_cost_usd: float = Field(..., description="Grand total cost")
    total_tokens: int = Field(..., description="Grand total tokens")
    total_requests: int = Field(..., description="Total request count")


@router.get("/costs", response_model=CostAggregationResponse)
async def get_costs(
    db: Annotated[AsyncSession, Depends(get_db)],
    group_by: Annotated[GroupBy, Query(description="How to group results")] = GroupBy.none,
    project_id: Annotated[str | None, Query(description="Filter by project ID")] = None,
    model: Annotated[str | None, Query(description="Filter by model name")] = None,
    agent_slug: Annotated[str | None, Query(description="Filter by agent slug")] = None,
    session_type: Annotated[str | None, Query(description="Filter by session type")] = None,
    external_id: Annotated[str | None, Query(description="Filter by external ID")] = None,
    start_date: Annotated[datetime | None, Query(description="Start date (inclusive)")] = None,
    end_date: Annotated[datetime | None, Query(description="End date (inclusive)")] = None,
    days: Annotated[
        int | None, Query(ge=1, le=365, description="Last N days (alternative to date range)")
    ] = None,
) -> CostAggregationResponse:
    """
    Get aggregated cost data with flexible grouping.

    Supports grouping by:
    - project: Group by project_id (via session)
    - model: Group by model name
    - day: Group by calendar day
    - week: Group by calendar week
    - month: Group by calendar month
    - none: No grouping, return totals only

    Query parameters:
    - group_by: How to group results
    - project_id: Filter by specific project
    - model: Filter by specific model
    - start_date/end_date: Date range filter
    - days: Shortcut for "last N days"
    """
    # Handle days shortcut
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    # Build base query
    aggregations: list[CostAggregation] = []
    query: Any

    if group_by == GroupBy.project:
        # Need to join with sessions to get project_id
        query = (
            select(
                Session.project_id.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .join(Session, CostLog.session_id == Session.id)
            .group_by(Session.project_id)
        )

        # Apply filters
        if project_id:
            query = query.where(Session.project_id == project_id)
        if model:
            query = query.where(CostLog.model.contains(model))
        if agent_slug:
            query = query.where(Session.agent_slug == agent_slug)
        if session_type:
            query = query.where(Session.session_type == session_type)
        if external_id:
            query = query.where(Session.external_id == external_id)
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=row.group_key or "unknown",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    elif group_by == GroupBy.agent_slug:
        # Group by agent_slug - join with sessions
        query = (
            select(
                Session.agent_slug.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .join(Session, CostLog.session_id == Session.id)
            .group_by(Session.agent_slug)
        )

        if project_id:
            query = query.where(Session.project_id == project_id)
        if model:
            query = query.where(CostLog.model.contains(model))
        if session_type:
            query = query.where(Session.session_type == session_type)
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=row.group_key or "unspecified",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    elif group_by == GroupBy.session_type:
        # Group by session_type - join with sessions
        query = (
            select(
                Session.session_type.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .join(Session, CostLog.session_id == Session.id)
            .group_by(Session.session_type)
        )

        if project_id:
            query = query.where(Session.project_id == project_id)
        if model:
            query = query.where(CostLog.model.contains(model))
        if agent_slug:
            query = query.where(Session.agent_slug == agent_slug)
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=str(row.group_key) if row.group_key else "completion",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    elif group_by == GroupBy.external_id:
        # Group by external_id - join with sessions
        query = (
            select(
                Session.external_id.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .join(Session, CostLog.session_id == Session.id)
            .group_by(Session.external_id)
        )

        if project_id:
            query = query.where(Session.project_id == project_id)
        if model:
            query = query.where(CostLog.model.contains(model))
        if agent_slug:
            query = query.where(Session.agent_slug == agent_slug)
        if session_type:
            query = query.where(Session.session_type == session_type)
        if external_id:
            query = query.where(Session.external_id == external_id)
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=row.group_key or "unspecified",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    elif group_by == GroupBy.model:
        query = select(
            CostLog.model.label("group_key"),
            func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
            func.sum(CostLog.input_tokens).label("input_tokens"),
            func.sum(CostLog.output_tokens).label("output_tokens"),
            func.sum(CostLog.cost_usd).label("total_cost"),
            func.count(CostLog.id).label("request_count"),
        ).group_by(CostLog.model)

        # Apply filters
        if model:
            query = query.where(CostLog.model.contains(model))
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)
        if project_id:
            # Need to join with sessions for project filter
            query = query.join(Session, CostLog.session_id == Session.id).where(
                Session.project_id == project_id
            )

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=row.group_key or "unknown",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    elif group_by in (GroupBy.day, GroupBy.week, GroupBy.month):
        # Date-based grouping
        if group_by == GroupBy.day:
            date_trunc = func.date_trunc("day", CostLog.created_at)
        elif group_by == GroupBy.week:
            date_trunc = func.date_trunc("week", CostLog.created_at)
        else:  # month
            date_trunc = func.date_trunc("month", CostLog.created_at)

        query = (
            select(
                date_trunc.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )

        # Apply filters
        if model:
            query = query.where(CostLog.model.contains(model))
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)
        if project_id:
            query = query.join(Session, CostLog.session_id == Session.id).where(
                Session.project_id == project_id
            )

        result = await db.execute(query)
        for row in result.all():
            aggregations.append(
                CostAggregation(
                    group_key=str(row.group_key),
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    else:  # GroupBy.none - just totals
        query = select(
            func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
            func.sum(CostLog.input_tokens).label("input_tokens"),
            func.sum(CostLog.output_tokens).label("output_tokens"),
            func.sum(CostLog.cost_usd).label("total_cost"),
            func.count(CostLog.id).label("request_count"),
        )

        # Apply filters
        if model:
            query = query.where(CostLog.model.contains(model))
        if start_date:
            query = query.where(CostLog.created_at >= start_date)
        if end_date:
            query = query.where(CostLog.created_at <= end_date)
        if project_id:
            query = query.join(Session, CostLog.session_id == Session.id).where(
                Session.project_id == project_id
            )

        result = await db.execute(query)
        row = result.one()
        if row.total_tokens:
            aggregations.append(
                CostAggregation(
                    group_key="total",
                    total_tokens=int(row.total_tokens or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    total_cost_usd=float(row.total_cost or 0.0),
                    request_count=int(row.request_count or 0),
                )
            )

    # Calculate grand totals
    grand_total_cost = sum(a.total_cost_usd for a in aggregations)
    grand_total_tokens = sum(a.total_tokens for a in aggregations)
    grand_total_requests = sum(a.request_count for a in aggregations)

    return CostAggregationResponse(
        aggregations=aggregations,
        total_cost_usd=grand_total_cost,
        total_tokens=grand_total_tokens,
        total_requests=grand_total_requests,
    )


# =============================================================================
# Truncation Analytics
# =============================================================================


class TruncationAggregation(BaseModel):
    """Aggregated truncation data for a group."""

    group_key: str = Field(..., description="Group identifier (model, day, etc.)")
    truncation_count: int = Field(..., description="Number of truncation events")
    avg_output_tokens: float = Field(..., description="Average output tokens when truncated")
    avg_max_tokens: float = Field(..., description="Average max_tokens requested")
    capped_count: int = Field(..., description="Events where max_tokens was capped to model limit")


class TruncationMetricsResponse(BaseModel):
    """Response for truncation metrics endpoint."""

    aggregations: list[TruncationAggregation] = Field(..., description="Aggregated truncation data")
    total_truncations: int = Field(..., description="Total truncation event count")
    truncation_rate: float = Field(
        ..., description="Truncation rate (truncations / total requests)"
    )
    recent_events: list[dict[str, Any]] = Field(default=[], description="Recent truncation events")


@router.get("/truncations", response_model=TruncationMetricsResponse)
async def get_truncations(
    db: Annotated[AsyncSession, Depends(get_db)],
    group_by: Annotated[GroupBy, Query(description="How to group results")] = GroupBy.model,
    model: Annotated[str | None, Query(description="Filter by model name")] = None,
    project_id: Annotated[str | None, Query(description="Filter by project ID")] = None,
    start_date: Annotated[datetime | None, Query(description="Start date (inclusive)")] = None,
    end_date: Annotated[datetime | None, Query(description="End date (inclusive)")] = None,
    days: Annotated[int | None, Query(ge=1, le=365, description="Last N days (default 7)")] = 7,
    include_recent: Annotated[bool, Query(description="Include recent truncation events")] = True,
    limit_recent: Annotated[int, Query(ge=1, le=100, description="Number of recent events")] = 10,
) -> TruncationMetricsResponse:
    """
    Get truncation metrics and analytics.

    Returns:
    - Aggregated truncation counts by model or time period
    - Truncation rate (percentage of requests that were truncated)
    - Recent truncation events for debugging
    """

    # Handle days shortcut (use naive datetime to match DB column)
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    aggregations: list[TruncationAggregation] = []

    # Build aggregation query based on group_by
    if group_by == GroupBy.model:
        query = select(
            TruncationEvent.model.label("group_key"),
            func.count(TruncationEvent.id).label("count"),
            func.avg(TruncationEvent.output_tokens).label("avg_output"),
            func.avg(TruncationEvent.max_tokens_requested).label("avg_max"),
            func.sum(TruncationEvent.was_capped).label("capped"),
        ).group_by(TruncationEvent.model)
    elif group_by in (GroupBy.day, GroupBy.week, GroupBy.month):
        if group_by == GroupBy.day:
            date_trunc = func.date_trunc("day", TruncationEvent.created_at)
        elif group_by == GroupBy.week:
            date_trunc = func.date_trunc("week", TruncationEvent.created_at)
        else:
            date_trunc = func.date_trunc("month", TruncationEvent.created_at)

        query = (
            select(
                date_trunc.label("group_key"),
                func.count(TruncationEvent.id).label("count"),
                func.avg(TruncationEvent.output_tokens).label("avg_output"),
                func.avg(TruncationEvent.max_tokens_requested).label("avg_max"),
                func.sum(TruncationEvent.was_capped).label("capped"),
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )
    else:  # none or project
        query = select(
            func.count(TruncationEvent.id).label("count"),
            func.avg(TruncationEvent.output_tokens).label("avg_output"),
            func.avg(TruncationEvent.max_tokens_requested).label("avg_max"),
            func.sum(TruncationEvent.was_capped).label("capped"),
        )

    # Apply filters
    if model:
        query = query.where(TruncationEvent.model.contains(model))
    if project_id:
        query = query.where(TruncationEvent.project_id == project_id)
    if start_date:
        query = query.where(TruncationEvent.created_at >= start_date)
    if end_date:
        query = query.where(TruncationEvent.created_at <= end_date)

    result = await db.execute(query)

    if group_by in (GroupBy.model, GroupBy.day, GroupBy.week, GroupBy.month):
        for row in result.all():
            count_val = getattr(row, "count", None)
            avg_output_val = getattr(row, "avg_output", None)
            avg_max_val = getattr(row, "avg_max", None)
            capped_val = getattr(row, "capped", None)
            aggregations.append(
                TruncationAggregation(
                    group_key=str(row.group_key),
                    truncation_count=int(count_val or 0),
                    avg_output_tokens=float(avg_output_val or 0),
                    avg_max_tokens=float(avg_max_val or 0),
                    capped_count=int(capped_val or 0),
                )
            )
    else:
        row = result.one()
        count_val = getattr(row, "count", None)
        if count_val:
            avg_output_val = getattr(row, "avg_output", None)
            avg_max_val = getattr(row, "avg_max", None)
            capped_val = getattr(row, "capped", None)
            aggregations.append(
                TruncationAggregation(
                    group_key="total",
                    truncation_count=int(count_val or 0),
                    avg_output_tokens=float(avg_output_val or 0),
                    avg_max_tokens=float(avg_max_val or 0),
                    capped_count=int(capped_val or 0),
                )
            )

    # Calculate total truncations
    total_truncations = sum(a.truncation_count for a in aggregations)

    # Calculate truncation rate (need total request count from cost_logs)
    count_query = select(func.count(CostLog.id))
    if start_date:
        count_query = count_query.where(CostLog.created_at >= start_date)
    if end_date:
        count_query = count_query.where(CostLog.created_at <= end_date)
    if model:
        count_query = count_query.where(CostLog.model.contains(model))

    count_result = await db.execute(count_query)
    total_requests = count_result.scalar() or 0

    truncation_rate = (total_truncations / total_requests * 100) if total_requests > 0 else 0.0

    # Get recent truncation events if requested
    recent_events: list[dict[str, Any]] = []
    if include_recent:
        recent_query = (
            select(TruncationEvent).order_by(TruncationEvent.created_at.desc()).limit(limit_recent)
        )
        if model:
            recent_query = recent_query.where(TruncationEvent.model.contains(model))
        if project_id:
            recent_query = recent_query.where(TruncationEvent.project_id == project_id)

        recent_result = await db.execute(recent_query)
        for event in recent_result.scalars().all():
            recent_events.append(
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

    return TruncationMetricsResponse(
        aggregations=aggregations,
        total_truncations=total_truncations,
        truncation_rate=truncation_rate,
        recent_events=recent_events,
    )
