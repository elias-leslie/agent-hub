"""
Analytics API endpoints for aggregated and raw export surfaces.

GET /analytics/costs - Aggregate cost data with grouping options.
GET /analytics/cost-logs - Raw cost-log export with cursor-based pagination.
GET /analytics/truncations - Truncation metrics and analytics.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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
    CostLogExportFilters,
    CostLogExportRow,
    TruncationFilters,
    get_recent_truncation_events,
    get_truncation_rate,
    list_cost_log_rows,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


class CostLogExportResponse(BaseModel):
    """Response for raw cost-log export."""

    rows: list[CostLogExportRow]
    next_after_id: int | None = None
    has_more: bool


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


@router.get("/cost-logs", response_model=CostLogExportResponse)
async def get_cost_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str | None, Query(description="Filter by project ID")] = None,
    after_id: Annotated[int | None, Query(ge=0, description="Resume after this cost-log ID")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Number of rows to return")] = 100,
    external_id: Annotated[str | None, Query(description="Filter by external ID")] = None,
    session_id: Annotated[str | None, Query(description="Filter by session ID")] = None,
    created_after: Annotated[datetime | None, Query(description="Created-at lower bound (inclusive)")] = None,
    created_before: Annotated[datetime | None, Query(description="Created-at upper bound (inclusive)")] = None,
) -> CostLogExportResponse:
    """Export raw cost-log rows in stable ascending ID order for ledger sync."""
    filters = CostLogExportFilters(
        project_id=project_id,
        after_id=after_id,
        limit=limit,
        external_id=external_id,
        session_id=session_id,
        created_after=created_after,
        created_before=created_before,
    )
    rows, next_after_id, has_more = await list_cost_log_rows(db, filters)
    return CostLogExportResponse(rows=rows, next_after_id=next_after_id, has_more=has_more)


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
