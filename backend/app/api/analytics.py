"""
Analytics API endpoints for cost aggregation.

GET /analytics/costs - Aggregate cost data with grouping options.
GET /analytics/truncations - Truncation metrics and analytics.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics_helpers import (
    CostAggregationResponse,
    GroupBy,
    TruncationMetricsResponse,
    dispatch_cost_aggregation,
    dispatch_truncation_aggregation,
)
from app.db import get_db
from app.services.analytics_service import (
    CostFilters,
    TruncationFilters,
    get_recent_truncation_events,
    get_truncation_rate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


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
    """Get aggregated cost data with flexible grouping by project, model, agent, time, etc."""
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    filters = CostFilters(
        project_id=project_id,
        model=model,
        agent_slug=agent_slug,
        session_type=session_type,
        external_id=external_id,
        start_date=start_date,
        end_date=end_date,
    )
    aggregations = await dispatch_cost_aggregation(db, group_by, filters)

    return CostAggregationResponse(
        aggregations=aggregations,
        total_cost_usd=sum(a.total_cost_usd for a in aggregations),
        total_tokens=sum(a.total_tokens for a in aggregations),
        total_requests=sum(a.request_count for a in aggregations),
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
    """Get truncation metrics: aggregated counts, rate, and recent events."""
    if days and not start_date:
        start_date = datetime.now(UTC) - timedelta(days=days)

    filters = TruncationFilters(
        model=model,
        project_id=project_id,
        start_date=start_date,
        end_date=end_date,
    )
    aggregations = await dispatch_truncation_aggregation(db, group_by, filters)
    total_truncations = sum(a.truncation_count for a in aggregations)
    truncation_rate = await get_truncation_rate(db, total_truncations, filters)
    recent_events: list[dict[str, Any]] = []
    if include_recent:
        recent_events = await get_recent_truncation_events(db, filters, limit_recent)

    return TruncationMetricsResponse(
        aggregations=aggregations,
        total_truncations=total_truncations,
        truncation_rate=truncation_rate,
        recent_events=recent_events,
    )
