"""Metrics endpoints for Access Control API."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_schemas import (
    EndpointSummary,
    RequestMetricsResponse,
    RequestMetricsSummary,
    ToolNameSummary,
    ToolTypeSummary,
)
from app.db import get_db
from app.models import RequestLog

router = APIRouter()


def _calculate_success_rate(success_count: int, total_count: int) -> float:
    """Calculate success rate percentage, defaulting to 100% if no requests."""
    return (success_count / total_count * 100) if total_count > 0 else 100.0


def _build_tool_name_summary(row: Any) -> ToolNameSummary:
    """Build ToolNameSummary from query result row."""
    total = row.request_count or 0
    success = row.success_count or 0
    return ToolNameSummary(
        tool_name=row.tool_name,
        count=total,
        avg_latency_ms=float(row.avg_latency or 0),
        success_rate=_calculate_success_rate(success, total),
    )


def _build_endpoint_summary(row: Any) -> EndpointSummary:
    """Build EndpointSummary from query result row."""
    total = row.request_count or 0
    success = row.success_count or 0
    return EndpointSummary(
        endpoint=row.endpoint,
        count=total,
        avg_latency_ms=float(row.avg_latency or 0),
        success_rate=_calculate_success_rate(success, total),
    )


@router.get("/metrics", response_model=RequestMetricsResponse)
async def get_request_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(default=24, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(default=10, ge=1, le=50, description="Max endpoints to return"),
) -> RequestMetricsResponse:
    """Get aggregated request metrics.

    Returns summary statistics, breakdown by tool type, and top endpoints.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    # Overall summary
    summary_query = select(
        func.count(RequestLog.id).label("total_requests"),
        func.avg(RequestLog.latency_ms).label("avg_latency"),
        func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
    ).where(RequestLog.created_at >= cutoff)

    summary_result = await db.execute(summary_query)
    summary_row = summary_result.one()

    total_requests = summary_row.total_requests or 0
    avg_latency = float(summary_row.avg_latency or 0)
    success_count = summary_row.success_count or 0
    success_rate = _calculate_success_rate(success_count, total_requests)

    # By tool type
    tool_type_query = (
        select(
            RequestLog.tool_type,
            func.count(RequestLog.id).label("request_count"),
        )
        .where(RequestLog.created_at >= cutoff)
        .group_by(RequestLog.tool_type)
        .order_by(func.count(RequestLog.id).desc())
    )

    tool_type_result = await db.execute(tool_type_query)
    by_tool_type = [
        ToolTypeSummary(tool_type=row.tool_type, count=row.request_count)
        for row in tool_type_result.all()
    ]

    # By tool name (specific commands/methods)
    tool_name_query = (
        select(
            RequestLog.tool_name,
            func.count(RequestLog.id).label("request_count"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
        )
        .where(RequestLog.created_at >= cutoff, RequestLog.tool_name.isnot(None))
        .group_by(RequestLog.tool_name)
        .order_by(func.count(RequestLog.id).desc())
        .limit(limit)
    )

    tool_name_result = await db.execute(tool_name_query)
    by_tool_name = [_build_tool_name_summary(row) for row in tool_name_result.all()]

    # By endpoint
    endpoint_query = (
        select(
            RequestLog.endpoint,
            func.count(RequestLog.id).label("request_count"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
        )
        .where(RequestLog.created_at >= cutoff)
        .group_by(RequestLog.endpoint)
        .order_by(func.count(RequestLog.id).desc())
        .limit(limit)
    )

    endpoint_result = await db.execute(endpoint_query)
    by_endpoint = [_build_endpoint_summary(row) for row in endpoint_result.all()]

    return RequestMetricsResponse(
        summary=RequestMetricsSummary(
            total_requests=total_requests,
            avg_latency_ms=avg_latency,
            success_rate=success_rate,
        ),
        by_tool_type=by_tool_type,
        by_tool_name=by_tool_name,
        by_endpoint=by_endpoint,
    )
