"""
Analytics API endpoints for cost aggregation.

GET /analytics/costs - Aggregate cost data with grouping options.
GET /analytics/truncations - Truncation metrics and analytics.
"""

import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.analytics_service import (
    CostAggregation,
    CostFilters,
    TruncationAggregation,
    TruncationFilters,
    aggregate_costs_by_agent,
    aggregate_costs_by_external_id,
    aggregate_costs_by_model,
    aggregate_costs_by_project,
    aggregate_costs_by_session_type,
    aggregate_costs_by_time,
    aggregate_costs_total,
    aggregate_truncations_by_model,
    aggregate_truncations_by_time,
    aggregate_truncations_total,
    get_recent_truncation_events,
    get_truncation_rate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


class GroupBy(StrEnum):
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


class CostAggregationResponse(BaseModel):
    """Response for cost aggregation endpoint."""

    aggregations: list[CostAggregation] = Field(..., description="Aggregated cost data")
    total_cost_usd: float = Field(..., description="Grand total cost")
    total_tokens: int = Field(..., description="Grand total tokens")
    total_requests: int = Field(..., description="Total request count")


class TruncationMetricsResponse(BaseModel):
    """Response for truncation metrics endpoint."""

    aggregations: list[TruncationAggregation] = Field(..., description="Aggregated truncation data")
    total_truncations: int = Field(..., description="Total truncation event count")
    truncation_rate: float = Field(
        ..., description="Truncation rate (truncations / total requests)"
    )
    recent_events: list[dict[str, Any]] = Field(default=[], description="Recent truncation events")


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
    - agent_slug: Group by agent slug
    - session_type: Group by session type
    - external_id: Group by external ID
    - day: Group by calendar day
    - week: Group by calendar week
    - month: Group by calendar month
    - none: No grouping, return totals only

    Query parameters:
    - group_by: How to group results
    - project_id: Filter by specific project
    - model: Filter by specific model
    - agent_slug: Filter by agent slug
    - session_type: Filter by session type
    - external_id: Filter by external ID
    - start_date/end_date: Date range filter
    - days: Shortcut for "last N days"
    """
    # Handle days shortcut
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    # Build filters
    filters = CostFilters(
        project_id=project_id,
        model=model,
        agent_slug=agent_slug,
        session_type=session_type,
        external_id=external_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Dispatch to appropriate aggregation function
    if group_by == GroupBy.project:
        aggregations = await aggregate_costs_by_project(db, filters)
    elif group_by == GroupBy.agent_slug:
        aggregations = await aggregate_costs_by_agent(db, filters)
    elif group_by == GroupBy.session_type:
        aggregations = await aggregate_costs_by_session_type(db, filters)
    elif group_by == GroupBy.external_id:
        aggregations = await aggregate_costs_by_external_id(db, filters)
    elif group_by == GroupBy.model:
        aggregations = await aggregate_costs_by_model(db, filters)
    elif group_by == GroupBy.day:
        aggregations = await aggregate_costs_by_time(db, filters, "day")
    elif group_by == GroupBy.week:
        aggregations = await aggregate_costs_by_time(db, filters, "week")
    elif group_by == GroupBy.month:
        aggregations = await aggregate_costs_by_time(db, filters, "month")
    else:  # GroupBy.none
        aggregations = await aggregate_costs_total(db, filters)

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
    # Handle days shortcut
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    # Build filters
    filters = TruncationFilters(
        model=model,
        project_id=project_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Dispatch to appropriate aggregation function
    if group_by == GroupBy.model:
        aggregations = await aggregate_truncations_by_model(db, filters)
    elif group_by in (GroupBy.day, GroupBy.week, GroupBy.month):
        period = group_by.value
        aggregations = await aggregate_truncations_by_time(db, filters, period)
    else:  # none or project
        aggregations = await aggregate_truncations_total(db, filters)

    # Calculate totals
    total_truncations = sum(a.truncation_count for a in aggregations)
    truncation_rate = await get_truncation_rate(db, total_truncations, filters)

    # Get recent events if requested
    recent_events = []
    if include_recent:
        recent_events = await get_recent_truncation_events(db, filters, limit_recent)

    return TruncationMetricsResponse(
        aggregations=aggregations,
        total_truncations=total_truncations,
        truncation_rate=truncation_rate,
        recent_events=recent_events,
    )
