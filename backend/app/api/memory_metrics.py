"""Memory metrics endpoints - for A/B testing and monitoring."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

router = APIRouter()


class VariantMetrics(BaseModel):
    """Aggregated metrics for a single variant."""

    variant: str = Field(..., description="Variant name")
    injection_count: int = Field(..., description="Total number of injections")
    success_count: int = Field(..., description="Number of successful tasks")
    fail_count: int = Field(..., description="Number of failed tasks")
    unknown_count: int = Field(..., description="Number with unknown outcome")
    success_rate: float = Field(..., description="Success rate (0-1)")
    citation_rate: float = Field(..., description="Memories cited / loaded ratio")
    avg_latency_ms: float = Field(..., description="Average injection latency")
    avg_tokens: float = Field(..., description="Average tokens injected")


class TimePeriodMetrics(BaseModel):
    """Metrics aggregated by time period."""

    period: str = Field(..., description="Time period (e.g., '2026-01-21', 'week-3')")
    injection_count: int
    avg_success_rate: float
    avg_citation_rate: float


class MetricsDashboardResponse(BaseModel):
    """Response from metrics dashboard endpoint."""

    total_injections: int = Field(..., description="Total injection count in period")
    period_start: str = Field(..., description="Start of analysis period")
    period_end: str = Field(..., description="End of analysis period")
    by_variant: list[VariantMetrics] = Field(..., description="Metrics broken down by variant")
    by_period: list[TimePeriodMetrics] = Field(..., description="Metrics by time period")
    overall_success_rate: float = Field(..., description="Overall success rate")
    overall_citation_rate: float = Field(..., description="Overall citation rate")


@router.get("/metrics", response_model=MetricsDashboardResponse)
async def get_memory_metrics(
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back")] = 7,
    period: Annotated[
        str,
        Query(description="Aggregation period: hour, day (default), week"),
    ] = "day",
    variant_filter: Annotated[
        str | None,
        Query(description="Filter by variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)"),
    ] = None,
    project_id_filter: Annotated[
        str | None,
        Query(description="Filter by project_id"),
    ] = None,
) -> MetricsDashboardResponse:
    """
    Get memory injection metrics for dashboard.

    Returns aggregated metrics including:
    - Injection counts by variant
    - Success and citation rates
    - Latency and token usage
    - Time-series breakdown by hour/day/week

    Useful for monitoring A/B test performance and tuning parameters.
    """
    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    try:
        async with session_factory() as session:
            query = select(MemoryInjectionMetric).where(
                MemoryInjectionMetric.created_at >= start_date,
                MemoryInjectionMetric.created_at <= end_date,
            )

            if variant_filter:
                query = query.where(MemoryInjectionMetric.variant == variant_filter)
            if project_id_filter:
                query = query.where(MemoryInjectionMetric.project_id == project_id_filter)

            result = await session.execute(query)
            records = result.scalars().all()

        # Aggregate by variant
        variant_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "success": 0,
                "fail": 0,
                "unknown": 0,
                "latency_sum": 0,
                "tokens_sum": 0,
                "loaded_sum": 0,
                "cited_sum": 0,
            }
        )

        # Aggregate by time period
        period_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "known": 0, "loaded": 0, "cited": 0}
        )

        for record in records:
            v = record.variant or "BASELINE"
            vd = variant_data[v]

            vd["count"] += 1
            if record.task_succeeded is True:
                vd["success"] += 1
            elif record.task_succeeded is False:
                vd["fail"] += 1
            else:
                vd["unknown"] += 1

            vd["latency_sum"] += record.injection_latency_ms or 0
            vd["tokens_sum"] += record.total_tokens or 0

            loaded = record.memories_loaded or []
            cited = record.memories_cited or []
            vd["loaded_sum"] += len(loaded) if isinstance(loaded, list) else 0
            vd["cited_sum"] += len(cited) if isinstance(cited, list) else 0

            # Time period aggregation
            created = record.created_at
            if period == "hour":
                period_key = created.strftime("%Y-%m-%d %H:00")
            elif period == "week":
                week_num = created.isocalendar()[1]
                period_key = f"{created.year}-W{week_num:02d}"
            else:  # day
                period_key = created.strftime("%Y-%m-%d")

            pd = period_data[period_key]
            pd["count"] += 1
            if record.task_succeeded is True:
                pd["success"] += 1
                pd["known"] += 1
            elif record.task_succeeded is False:
                pd["known"] += 1
            pd["loaded"] += len(loaded) if isinstance(loaded, list) else 0
            pd["cited"] += len(cited) if isinstance(cited, list) else 0

        # Build variant metrics
        by_variant = []
        for variant, data in sorted(variant_data.items()):
            count = data["count"]
            known = data["success"] + data["fail"]
            success_rate = data["success"] / known if known > 0 else 0.0
            citation_rate = (
                data["cited_sum"] / data["loaded_sum"] if data["loaded_sum"] > 0 else 0.0
            )

            by_variant.append(
                VariantMetrics(
                    variant=variant,
                    injection_count=count,
                    success_count=data["success"],
                    fail_count=data["fail"],
                    unknown_count=data["unknown"],
                    success_rate=round(success_rate, 3),
                    citation_rate=round(citation_rate, 3),
                    avg_latency_ms=round(data["latency_sum"] / count, 1) if count > 0 else 0.0,
                    avg_tokens=round(data["tokens_sum"] / count, 1) if count > 0 else 0.0,
                )
            )

        # Build period metrics
        by_period = []
        for period_key in sorted(period_data.keys()):
            data = period_data[period_key]
            success_rate = data["success"] / data["known"] if data["known"] > 0 else 0.0
            citation_rate = data["cited"] / data["loaded"] if data["loaded"] > 0 else 0.0

            by_period.append(
                TimePeriodMetrics(
                    period=period_key,
                    injection_count=data["count"],
                    avg_success_rate=round(success_rate, 3),
                    avg_citation_rate=round(citation_rate, 3),
                )
            )

        # Overall metrics
        total_success = sum(d["success"] for d in variant_data.values())
        total_known = sum(d["success"] + d["fail"] for d in variant_data.values())
        total_loaded = sum(d["loaded_sum"] for d in variant_data.values())
        total_cited = sum(d["cited_sum"] for d in variant_data.values())

        overall_success = total_success / total_known if total_known > 0 else 0.0
        overall_citation = total_cited / total_loaded if total_loaded > 0 else 0.0

        return MetricsDashboardResponse(
            total_injections=len(records),
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            by_variant=by_variant,
            by_period=by_period,
            overall_success_rate=round(overall_success, 3),
            overall_citation_rate=round(overall_citation, 3),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metrics: {e}",
        ) from e
