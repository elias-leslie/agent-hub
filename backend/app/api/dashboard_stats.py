"""
Dashboard statistics aggregation endpoint.

Provides a single endpoint that aggregates all dashboard metrics from:
- request_logs: Request volume, latency, success rate
- sessions: Active session count
- cost_logs: Total costs
- memory_injection_metrics: Memory system health
- truncation_events: Truncation rate
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CostLog, MemoryInjectionMetric, RequestLog, Session, TruncationEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

class RequestMetrics(BaseModel):
    """Request performance metrics."""

    total_requests: int = Field(..., description="Total request count")
    avg_latency_ms: float = Field(..., description="Average latency in ms")
    p50_latency_ms: float = Field(..., description="P50 latency in ms")
    p95_latency_ms: float = Field(..., description="P95 latency in ms")
    success_rate: float = Field(..., description="Success rate (0-100)")
    error_count: int = Field(..., description="Number of errors (4xx/5xx)")
    timeout_count: int = Field(0, description="Number of timed-out requests")
    fallback_count: int = Field(0, description="Number of requests that used fallback")
    fallback_success_rate: float = Field(100.0, description="Success rate of fallback requests (0-100)")


class MemoryMetrics(BaseModel):
    """Memory injection metrics."""

    total_injections: int = Field(..., description="Total memory injections")
    avg_latency_ms: float = Field(..., description="Average injection latency")
    avg_tokens: float = Field(..., description="Average tokens injected")
    total_mandates: int = Field(..., description="Total mandates injected")
    total_guardrails: int = Field(..., description="Total guardrails injected")
    total_references: int = Field(..., description="Total selected references injected")
    total_reference_index_entries: int = Field(..., description="Total passive reference index entries injected")
    total_reference_citations: int = Field(..., description="Total selected references later cited")


class TruncationMetrics(BaseModel):
    """Output truncation metrics."""

    total_truncations: int = Field(..., description="Total truncation events")
    truncation_rate: float = Field(..., description="Truncation rate (0-100)")
    avg_output_tokens: float = Field(..., description="Average output tokens when truncated")


class ModelBreakdown(BaseModel):
    """Model-specific metrics."""

    model: str
    avg_latency_ms: float
    request_count: int


class DashboardStatsResponse(BaseModel):
    """Complete dashboard statistics response."""

    # Time range info
    period_days: int = Field(..., description="Number of days in period")
    period_start: str = Field(..., description="Period start timestamp")
    period_end: str = Field(..., description="Period end timestamp")

    # Request metrics
    requests: RequestMetrics

    # Memory metrics
    memory: MemoryMetrics

    # Truncation metrics
    truncations: TruncationMetrics

    # Model breakdown
    by_model: list[ModelBreakdown]

    # Session metrics
    active_sessions: int = Field(..., description="Currently active sessions")
    total_sessions: int = Field(..., description="Total sessions in period")

    # Cost metrics
    total_cost_usd: float = Field(..., description="Total cost in USD")
    total_tokens: int = Field(..., description="Total tokens used")


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90, description="Number of days to include")] = 7,
) -> DashboardStatsResponse:
    """
    Get aggregated dashboard statistics.

    Returns comprehensive metrics for the dashboard including:
    - Request volume and latency from request_logs
    - Memory injection metrics
    - Truncation rates
    - Cost totals
    - Active sessions
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    # -------------------------------------------------------------------------
    # Request metrics from request_logs
    # -------------------------------------------------------------------------
    # Basic aggregates
    request_query = select(
        func.count(RequestLog.id).label("total"),
        func.avg(RequestLog.latency_ms).label("avg_latency"),
        func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
        func.sum(case((RequestLog.timed_out.is_(True), 1), else_=0)).label("timeout_count"),
        func.sum(case((RequestLog.used_fallback.is_(True), 1), else_=0)).label("fallback_count"),
        func.sum(case(
            (RequestLog.used_fallback.is_(True) & (RequestLog.status_code < 400), 1), else_=0,
        )).label("fallback_success"),
    ).where(RequestLog.created_at >= cutoff)

    request_result = await db.execute(request_query)
    req_row = request_result.one()

    total_requests = req_row.total or 0
    success_count = req_row.success_count or 0
    error_count = total_requests - success_count
    timeout_count = int(req_row.timeout_count or 0)
    fallback_count = int(req_row.fallback_count or 0)
    fallback_success = int(req_row.fallback_success or 0)
    fallback_success_rate = (fallback_success / fallback_count * 100) if fallback_count > 0 else 100.0

    # Percentiles require separate query (PostgreSQL specific)
    p50_latency = 0.0
    p95_latency = 0.0
    if total_requests > 0:
        try:
            # Use percentile_cont for PostgreSQL
            percentile_query = select(
                func.percentile_cont(0.5).within_group(RequestLog.latency_ms).label("p50"),
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
            ).where(RequestLog.created_at >= cutoff, RequestLog.latency_ms.isnot(None))

            perc_result = await db.execute(percentile_query)
            perc_row = perc_result.one()
            p50_latency = float(perc_row.p50 or 0)
            p95_latency = float(perc_row.p95 or 0)
        except Exception:
            logger.debug("percentile_cont query failed, using defaults", exc_info=True)

    requests = RequestMetrics(
        total_requests=total_requests,
        avg_latency_ms=float(req_row.avg_latency or 0),
        p50_latency_ms=p50_latency,
        p95_latency_ms=p95_latency,
        success_rate=(success_count / total_requests * 100) if total_requests > 0 else 100.0,
        error_count=error_count,
        timeout_count=timeout_count,
        fallback_count=fallback_count,
        fallback_success_rate=fallback_success_rate,
    )

    # -------------------------------------------------------------------------
    # Model breakdown from request_logs
    # -------------------------------------------------------------------------
    model_query = (
        select(
            func.coalesce(RequestLog.model, "unknown").label("model"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count(RequestLog.id).label("request_count"),
        )
        .where(RequestLog.created_at >= cutoff)
        .group_by(RequestLog.model)
        .order_by(func.count(RequestLog.id).desc())
        .limit(10)
    )

    model_result = await db.execute(model_query)
    by_model = [
        ModelBreakdown(
            model=row.model or "unknown",
            avg_latency_ms=float(row.avg_latency or 0),
            request_count=row.request_count or 0,
        )
        for row in model_result.all()
    ]

    # -------------------------------------------------------------------------
    # Memory injection metrics
    # -------------------------------------------------------------------------
    memory_query = select(
        func.count(MemoryInjectionMetric.id).label("total"),
        func.avg(MemoryInjectionMetric.injection_latency_ms).label("avg_latency"),
        func.avg(MemoryInjectionMetric.total_tokens).label("avg_tokens"),
        func.sum(MemoryInjectionMetric.mandates_count).label("total_mandates"),
        func.sum(MemoryInjectionMetric.guardrails_count).label("total_guardrails"),
        func.sum(MemoryInjectionMetric.reference_count).label("total_refs"),
        func.sum(MemoryInjectionMetric.reference_index_count).label("total_ref_index"),
        func.sum(MemoryInjectionMetric.reference_cited_count).label("total_ref_cited"),
    ).where(MemoryInjectionMetric.created_at >= cutoff)

    memory_result = await db.execute(memory_query)
    mem_row = memory_result.one()

    memory = MemoryMetrics(
        total_injections=mem_row.total or 0,
        avg_latency_ms=float(mem_row.avg_latency or 0),
        avg_tokens=float(mem_row.avg_tokens or 0),
        total_mandates=int(mem_row.total_mandates or 0),
        total_guardrails=int(mem_row.total_guardrails or 0),
        total_references=int(mem_row.total_refs or 0),
        total_reference_index_entries=int(mem_row.total_ref_index or 0),
        total_reference_citations=int(mem_row.total_ref_cited or 0),
    )

    # -------------------------------------------------------------------------
    # Truncation metrics
    # -------------------------------------------------------------------------
    trunc_query = select(
        func.count(TruncationEvent.id).label("total"),
        func.avg(TruncationEvent.output_tokens).label("avg_output"),
    ).where(TruncationEvent.created_at >= cutoff)

    trunc_result = await db.execute(trunc_query)
    trunc_row = trunc_result.one()

    total_truncations = trunc_row.total or 0
    truncation_rate = (total_truncations / total_requests * 100) if total_requests > 0 else 0

    truncations = TruncationMetrics(
        total_truncations=total_truncations,
        truncation_rate=truncation_rate,
        avg_output_tokens=float(trunc_row.avg_output or 0),
    )

    # -------------------------------------------------------------------------
    # Session counts
    # -------------------------------------------------------------------------
    active_query = select(func.count(Session.id)).where(Session.status == "active")
    active_result = await db.execute(active_query)
    active_sessions = active_result.scalar() or 0

    total_sessions_query = select(func.count(Session.id)).where(Session.created_at >= cutoff)
    total_sessions_result = await db.execute(total_sessions_query)
    total_sessions = total_sessions_result.scalar() or 0

    # -------------------------------------------------------------------------
    # Cost totals
    # -------------------------------------------------------------------------
    cost_query = select(
        func.coalesce(func.sum(CostLog.cost_usd), 0).label("total_cost"),
        func.coalesce(func.sum(CostLog.input_tokens + CostLog.output_tokens), 0).label(
            "total_tokens"
        ),
    ).where(CostLog.created_at >= cutoff)

    cost_result = await db.execute(cost_query)
    cost_row = cost_result.one()

    return DashboardStatsResponse(
        period_days=days,
        period_start=cutoff.isoformat(),
        period_end=now.isoformat(),
        requests=requests,
        memory=memory,
        truncations=truncations,
        by_model=by_model,
        active_sessions=active_sessions,
        total_sessions=total_sessions,
        total_cost_usd=float(cost_row.total_cost or 0),
        total_tokens=int(cost_row.total_tokens or 0),
    )


class ProviderHealthInfo(BaseModel):
    """Live provider health information."""

    provider: str
    state: str
    latency_ms: float
    availability: float
    consecutive_failures: int
    last_error: str | None


class ProviderHealthResponse(BaseModel):
    """Response for provider health endpoint."""

    providers: list[ProviderHealthInfo]


@router.get("/provider-health", response_model=ProviderHealthResponse)
async def get_provider_health() -> ProviderHealthResponse:
    """Get passive provider health for registered pi-mono providers."""
    from app.llm.api_registry import get_api_providers

    providers = [
        ProviderHealthInfo(
            provider=str(provider.api),
            state="healthy",
            latency_ms=0.0,
            availability=100.0,
            consecutive_failures=0,
            last_error=None,
        )
        for provider in get_api_providers()
    ]

    return ProviderHealthResponse(providers=providers)
