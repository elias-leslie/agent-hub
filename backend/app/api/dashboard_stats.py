"""
Dashboard statistics aggregation endpoint.

Provides a single endpoint that aggregates dashboard metrics from:
- request_logs: model-call volume, latency and success (``POST /api/complete``
  only, which serves both buffered and streaming completions)
- sessions: Active session count
- cost_logs: Metered spend (API-billed calls only)
- memory_injection_metrics: Memory injection counts, keeping explicitly
  selected references separate from passive reference-index entries
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CostLog, MemoryInjectionMetric, RequestLog, Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Request telemetry rows that represent a model call. Streaming completions are
# served by the same endpoint (``stream: true``), so this covers both paths.
MODEL_CALL_ENDPOINT = "/api/complete"
MODEL_CALL_METHOD = "POST"


def _model_call_filter(cutoff: datetime) -> tuple:
    return (
        RequestLog.endpoint == MODEL_CALL_ENDPOINT,
        RequestLog.method == MODEL_CALL_METHOD,
        RequestLog.created_at >= cutoff,
    )


class RequestMetrics(BaseModel):
    """Model-call performance metrics (``POST /api/complete`` rows only)."""

    total_requests: int = Field(..., description="Model calls in the period")
    avg_latency_ms: float | None = Field(None, description="Average latency in ms; null with no calls")
    p50_latency_ms: float | None = Field(None, description="P50 latency in ms; null with no calls")
    p95_latency_ms: float | None = Field(None, description="P95 latency in ms; null with no calls")
    success_rate: float | None = Field(None, description="Success rate (0-100); null with no calls")
    error_count: int = Field(..., description="Model calls with HTTP status >= 400")


class DailyRequestCount(BaseModel):
    """Model calls for one UTC day."""

    date: str = Field(..., description="UTC date (YYYY-MM-DD)")
    requests: int
    errors: int


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


class ModelBreakdown(BaseModel):
    """Model-specific model-call metrics."""

    model: str
    avg_latency_ms: float
    request_count: int


class DashboardStatsResponse(BaseModel):
    """Complete dashboard statistics response."""

    # Time range info
    period_days: int = Field(..., description="Number of days in period")
    period_start: str = Field(..., description="Period start timestamp")
    period_end: str = Field(..., description="Period end timestamp")

    # Model-call metrics
    requests: RequestMetrics
    requests_by_day: list[DailyRequestCount] = Field(
        ..., description="Model calls per UTC day, same population as requests"
    )

    # Memory metrics
    memory: MemoryMetrics

    # Model breakdown
    by_model: list[ModelBreakdown]

    # Session metrics
    active_sessions: int = Field(..., description="Currently active sessions")
    total_sessions: int = Field(..., description="Total sessions in period")

    # Cost metrics
    total_cost_usd: float = Field(..., description="Metered spend in USD (API-billed calls only)")
    total_tokens: int = Field(..., description="Tokens on metered (API-billed) calls")


async def _request_metrics(db: AsyncSession, cutoff: datetime) -> RequestMetrics:
    row = (
        await db.execute(
            select(
                func.count(RequestLog.id).label("total"),
                func.sum(case((RequestLog.status_code < 400, 1), else_=0)).label("success_count"),
                func.avg(RequestLog.latency_ms).label("avg_latency"),
                func.percentile_cont(0.5).within_group(RequestLog.latency_ms).label("p50"),
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
            ).where(*_model_call_filter(cutoff))
        )
    ).one()
    total = int(row.total or 0)
    success = int(row.success_count or 0)
    if total == 0:
        return RequestMetrics(total_requests=0, error_count=0)
    return RequestMetrics(
        total_requests=total,
        avg_latency_ms=None if row.avg_latency is None else float(row.avg_latency),
        p50_latency_ms=None if row.p50 is None else float(row.p50),
        p95_latency_ms=None if row.p95 is None else float(row.p95),
        success_rate=success / total * 100,
        error_count=total - success,
    )


async def _requests_by_day(db: AsyncSession, cutoff: datetime, now: datetime) -> list[DailyRequestCount]:
    day = cast(func.timezone("UTC", RequestLog.created_at), Date)
    rows = (
        await db.execute(
            select(
                day.label("day"),
                func.count(RequestLog.id).label("requests"),
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)).label("errors"),
            )
            .where(*_model_call_filter(cutoff))
            .group_by(day)
        )
    ).all()
    counts = {row.day: (int(row.requests or 0), int(row.errors or 0)) for row in rows}
    first, last = cutoff.astimezone(UTC).date(), now.astimezone(UTC).date()
    series = []
    current = first
    while current <= last:
        requests, errors = counts.get(current, (0, 0))
        series.append(DailyRequestCount(date=current.isoformat(), requests=requests, errors=errors))
        current += timedelta(days=1)
    return series


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90, description="Number of days to include")] = 7,
) -> DashboardStatsResponse:
    """
    Get aggregated dashboard statistics.

    Request, latency, success and per-model figures count model calls only
    (``POST /api/complete``). Dashboard UI traffic and other HTTP endpoints are
    excluded. Cost covers metered (API-billed) calls recorded in cost_logs.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    requests = await _request_metrics(db, cutoff)
    requests_by_day = await _requests_by_day(db, cutoff, now)

    model_query = (
        select(
            func.coalesce(RequestLog.model, "unknown").label("model"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count(RequestLog.id).label("request_count"),
        )
        .where(*_model_call_filter(cutoff))
        .group_by(RequestLog.model)
        .order_by(func.count(RequestLog.id).desc())
        .limit(10)
    )
    by_model = [
        ModelBreakdown(
            model=row.model or "unknown",
            avg_latency_ms=float(row.avg_latency or 0),
            request_count=row.request_count or 0,
        )
        for row in (await db.execute(model_query)).all()
    ]

    # -------------------------------------------------------------------------
    # Memory injection metrics (selected references and passive index entries
    # stay separate counts)
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
    mem_row = (await db.execute(memory_query)).one()
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

    active_sessions = (
        await db.execute(select(func.count(Session.id)).where(Session.status == "active"))
    ).scalar() or 0
    total_sessions = (
        await db.execute(select(func.count(Session.id)).where(Session.created_at >= cutoff))
    ).scalar() or 0

    cost_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(CostLog.cost_usd), 0).label("total_cost"),
                func.coalesce(func.sum(CostLog.input_tokens + CostLog.output_tokens), 0).label("total_tokens"),
            ).where(CostLog.created_at >= cutoff)
        )
    ).one()

    return DashboardStatsResponse(
        period_days=days,
        period_start=cutoff.isoformat(),
        period_end=now.isoformat(),
        requests=requests,
        requests_by_day=requests_by_day,
        memory=memory,
        by_model=by_model,
        active_sessions=active_sessions,
        total_sessions=total_sessions,
        total_cost_usd=float(cost_row.total_cost or 0),
        total_tokens=int(cost_row.total_tokens or 0),
    )


class ProviderHealthInfo(BaseModel):
    """Provider readiness plus its last 24 hours of completion outcomes."""

    provider: str
    state: str = Field(..., description="ready/unavailable, or healthy/degraded once calls were seen")
    latency_ms: float | None = Field(None, description="Average completion latency; null with no calls")
    availability: float | None = Field(None, description="Share of calls without a provider failure (0-1)")
    consecutive_failures: int = 0
    recent_calls: int = Field(0, description="Completion calls in the last 24 hours")
    recent_failures: int = Field(0, description="Provider failures (5xx/429) in the last 24 hours")
    last_error: str | None


class ProviderHealthResponse(BaseModel):
    """Response for provider health endpoint."""

    providers: list[ProviderHealthInfo]


@router.get("/provider-health", response_model=ProviderHealthResponse)
async def get_provider_health(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProviderHealthResponse:
    """Readiness of each routing provider and its recent completion outcomes."""
    from app.api.health_logic import provider_outcome_report

    providers = []
    for status, outcome in await provider_outcome_report(db):
        health = status.health
        if health is None or outcome is None:
            providers.append(
                ProviderHealthInfo(
                    provider=status.name,
                    state="ready" if status.available else "unavailable",
                    last_error=status.error,
                )
            )
            continue
        providers.append(
            ProviderHealthInfo(
                provider=status.name,
                state=health.state,
                latency_ms=health.latency_ms if outcome.latency_samples else None,
                availability=health.availability,
                consecutive_failures=health.consecutive_failures,
                recent_calls=outcome.calls,
                recent_failures=outcome.failures,
                last_error=status.error or health.last_error,
            )
        )
    return ProviderHealthResponse(providers=providers)
