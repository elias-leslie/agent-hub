"""Memory analytics service providing explicit current-state and recent-activity data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db import async_session
from app.models import MemoryInjectionMetric
from app.models.memory import UsageStatLog

from .analytics_models import (
    InjectionMetricsSummary,
    MemoryAnalyticsActivity,
    MemoryAnalyticsDashboard,
    MemoryAnalyticsState,
    OutcomeSummary,
    ScopeDistribution,
    TierDistribution,
    TimePeriodMetrics,
    TopMemory,
    UsageTotals,
    VariantMetrics,
)
from .analytics_queries import (
    get_avg_lifecycle_score,
    get_avg_utility_score,
    get_lifecycle_by_tier,
    get_scope_distribution,
    get_tier_changes_summary,
    get_tier_distribution,
    get_top_memories_query,
    get_usage_aggregates,
)

logger = logging.getLogger(__name__)


def _determine_activity_period(lookback_delta: timedelta) -> str:
    """Use hourly buckets for short windows and daily buckets otherwise."""
    if lookback_delta <= timedelta(days=1):
        return "hour"
    return "day"


def _normalize_usage_totals(raw: dict[str, int]) -> UsageTotals:
    """Convert raw usage mappings into the dashboard schema."""
    return UsageTotals(
        loaded=raw.get("loaded", 0),
        cited=raw.get("referenced", raw.get("cited", 0)),
        helpful=raw.get("helpful", 0),
        harmful=raw.get("harmful", 0),
        success=raw.get("success", 0),
    )


def _format_period_key(created_at: datetime, period: str) -> str:
    """Return a stable period key for aggregation."""
    if period == "hour":
        return created_at.strftime("%Y-%m-%d %H:00")
    if period == "week":
        week_num = created_at.isocalendar()[1]
        return f"{created_at.year}-W{week_num:02d}"
    return created_at.strftime("%Y-%m-%d")


def _build_outcome_summary(records: list[dict[str, Any]]) -> OutcomeSummary:
    """Summarize outcome coverage and success for a set of injection records."""
    success_count = sum(1 for record in records if record.get("task_succeeded") is True)
    fail_count = sum(1 for record in records if record.get("task_succeeded") is False)
    unknown_count = sum(1 for record in records if record.get("task_succeeded") is None)
    known_count = success_count + fail_count
    total = known_count + unknown_count
    coverage_rate = known_count / total if total > 0 else 0.0
    success_rate = success_count / known_count if known_count > 0 else 0.0
    return OutcomeSummary(
        success_count=success_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        known_count=known_count,
        coverage_rate=coverage_rate,
        success_rate=success_rate,
    )


async def get_recent_usage_totals(lookback_delta: timedelta) -> dict[str, int]:
    """Aggregate usage_stat_log rows inside the requested window."""
    cutoff = datetime.now(UTC) - lookback_delta
    stmt = (
        select(UsageStatLog.metric_type, func.coalesce(func.sum(UsageStatLog.value), 0))
        .where(UsageStatLog.timestamp >= cutoff)
        .group_by(UsageStatLog.metric_type)
    )

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    totals = {"loaded": 0, "referenced": 0, "helpful": 0, "harmful": 0, "success": 0}
    for metric_type, value in rows:
        if metric_type in totals:
            totals[metric_type] = int(value or 0)
    return totals


async def get_injection_metrics_summary(
    lookback_delta: timedelta,
    *,
    period: str,
    variant_filter: str | None = None,
    project_id_filter: str | None = None,
) -> InjectionMetricsSummary:
    """Aggregate memory injection metrics for the requested activity window."""
    if period not in {"hour", "day", "week"}:
        msg = f"Invalid period: {period}"
        raise ValueError(msg)

    end_date = datetime.now(UTC)
    start_date = end_date - lookback_delta

    query = select(MemoryInjectionMetric).where(
        MemoryInjectionMetric.created_at >= start_date,
        MemoryInjectionMetric.created_at <= end_date,
    )
    if variant_filter:
        query = query.where(MemoryInjectionMetric.variant == variant_filter)
    if project_id_filter:
        query = query.where(MemoryInjectionMetric.project_id == project_id_filter)

    async with async_session() as session:
        result = await session.execute(query)
        raw_records = result.scalars().all()

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
    period_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "success": 0, "known": 0, "loaded": 0, "cited": 0}
    )
    normalized_records: list[dict[str, Any]] = []

    for record in raw_records:
        loaded = record.memories_loaded or []
        cited = record.memories_cited or []
        task_succeeded = record.task_succeeded
        normalized_records.append({"task_succeeded": task_succeeded})

        variant = record.variant or "BASELINE"
        variant_bucket = variant_data[variant]
        variant_bucket["count"] += 1
        if task_succeeded is True:
            variant_bucket["success"] += 1
        elif task_succeeded is False:
            variant_bucket["fail"] += 1
        else:
            variant_bucket["unknown"] += 1
        variant_bucket["latency_sum"] += record.injection_latency_ms or 0
        variant_bucket["tokens_sum"] += record.total_tokens or 0
        variant_bucket["loaded_sum"] += len(loaded) if isinstance(loaded, list) else 0
        variant_bucket["cited_sum"] += len(cited) if isinstance(cited, list) else 0

        period_key = _format_period_key(record.created_at, period)
        period_bucket = period_data[period_key]
        period_bucket["count"] += 1
        if task_succeeded is True:
            period_bucket["success"] += 1
            period_bucket["known"] += 1
        elif task_succeeded is False:
            period_bucket["known"] += 1
        period_bucket["loaded"] += len(loaded) if isinstance(loaded, list) else 0
        period_bucket["cited"] += len(cited) if isinstance(cited, list) else 0

    by_variant = []
    for variant, data in sorted(variant_data.items()):
        count = data["count"]
        known = data["success"] + data["fail"]
        success_rate = data["success"] / known if known > 0 else 0.0
        citation_rate = data["cited_sum"] / data["loaded_sum"] if data["loaded_sum"] > 0 else 0.0
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

    by_period = []
    for period_key in sorted(period_data):
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

    outcomes = _build_outcome_summary(normalized_records)
    total_loaded = sum(data["loaded_sum"] for data in variant_data.values())
    total_cited = sum(data["cited_sum"] for data in variant_data.values())

    return InjectionMetricsSummary(
        total_injections=len(raw_records),
        period_start=start_date.isoformat(),
        period_end=end_date.isoformat(),
        period_granularity=period,
        by_variant=by_variant,
        by_period=by_period,
        overall_success_rate=round(outcomes.success_rate, 3),
        overall_citation_rate=round(total_cited / total_loaded, 3) if total_loaded > 0 else 0.0,
        outcomes=outcomes,
    )


async def get_top_memories(
    group_id: str | None = None,
    sort_by: str = "utility_score",
    limit: int = 8,
) -> list[TopMemory]:
    """Return top-performing memories for the dedicated endpoint."""
    return await get_top_memories_query(group_id, sort_by, limit)


async def _fetch_state_data(
    group_id: str | None,
    top_memories_sort_by: str,
    top_memories_limit: int,
) -> tuple[
    list[TierDistribution],
    list[ScopeDistribution],
    UsageTotals,
    float,
    float,
    dict[str, float],
    list[TopMemory],
]:
    """Fetch all state-oriented analytics."""
    tier_dist = await get_tier_distribution(group_id)
    scope_dist = await get_scope_distribution(group_id)
    usage_totals = _normalize_usage_totals(await get_usage_aggregates(group_id))
    avg_utility = await get_avg_utility_score(group_id)
    avg_lifecycle = await get_avg_lifecycle_score(group_id)
    lifecycle_tiers = await get_lifecycle_by_tier(group_id)
    top_memories = await get_top_memories_query(group_id, top_memories_sort_by, top_memories_limit)
    return (
        tier_dist,
        scope_dist,
        usage_totals,
        avg_utility,
        avg_lifecycle,
        lifecycle_tiers,
        top_memories,
    )


async def get_memory_dashboard(
    *,
    group_id: str | None = None,
    lookback_delta: timedelta,
    lookback_label: str,
    top_memories_sort_by: str = "utility_score",
    top_memories_limit: int = 8,
) -> MemoryAnalyticsDashboard:
    """Return the explicit analytics dashboard payload for the memory page."""
    period = _determine_activity_period(lookback_delta)
    (
        tier_dist,
        scope_dist,
        state_usage_totals,
        avg_utility,
        avg_lifecycle,
        lifecycle_tiers,
        top_memories,
    ) = await _fetch_state_data(group_id, top_memories_sort_by, top_memories_limit)

    activity_usage_totals = _normalize_usage_totals(await get_recent_usage_totals(lookback_delta))
    injection_metrics = await get_injection_metrics_summary(lookback_delta, period=period)
    tier_changes = await get_tier_changes_summary(lookback_delta=lookback_delta)

    state = MemoryAnalyticsState(
        total_episodes=sum(t.count for t in tier_dist),
        tier_distribution=tier_dist,
        scope_distribution=scope_dist,
        usage_totals=state_usage_totals,
        avg_utility_score=round(avg_utility, 3),
        avg_lifecycle_score=round(avg_lifecycle, 3),
        lifecycle_by_tier=lifecycle_tiers,
        top_memories=top_memories,
    )
    activity = MemoryAnalyticsActivity(
        lookback=lookback_label,
        usage_totals=activity_usage_totals,
        injection_metrics=injection_metrics,
        tier_changes=tier_changes,
    )
    return MemoryAnalyticsDashboard(state=state, activity=activity)
