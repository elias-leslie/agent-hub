"""
Analytics API endpoints for cost aggregation.

GET /analytics/costs - Aggregate cost data with grouping options.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CostLog, Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


class GroupBy(str, Enum):
    """Grouping options for cost aggregation."""

    project = "project"
    model = "model"
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
    group_by: GroupBy = Query(default=GroupBy.none, description="How to group results"),
    project_id: str | None = Query(default=None, description="Filter by project ID"),
    model: str | None = Query(default=None, description="Filter by model name"),
    start_date: datetime | None = Query(default=None, description="Start date (inclusive)"),
    end_date: datetime | None = Query(default=None, description="End date (inclusive)"),
    days: int | None = Query(default=None, ge=1, le=365, description="Last N days (alternative to date range)"),
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
        start_date = datetime.utcnow() - timedelta(days=days)

    # Build base query
    aggregations: list[CostAggregation] = []

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

    elif group_by == GroupBy.model:
        query = (
            select(
                CostLog.model.label("group_key"),
                func.sum(CostLog.input_tokens + CostLog.output_tokens).label("total_tokens"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
                func.sum(CostLog.cost_usd).label("total_cost"),
                func.count(CostLog.id).label("request_count"),
            )
            .group_by(CostLog.model)
        )

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
