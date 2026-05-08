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

from ._analytics_utilization import get_memory_utilization_summary
from .analytics_models import (
    InjectionMetricsSummary,
    MemoryAnalyticsActivity,
    MemoryAnalyticsDashboard,
    MemoryAnalyticsState,
    MemoryUtilizationMetrics,
    OutcomeSummary,
    StUsageCommandMetricModel,
    StUsageQuickEntryModel,
    StUsageSummary,
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
from .st_usage_memory import StUsageMemory, get_recent_st_usage_memory

logger = logging.getLogger(__name__)


def _project_id_filter_from_group_id(group_id: str | None) -> str | None:
    """Derive a project filter from canonical project group ids."""
    if not group_id or not group_id.startswith("project-"):
        return None
    return group_id[len("project-") :]


def _normalize_usage_totals(raw: dict[str, int]) -> UsageTotals:
    """Convert raw usage mappings into the dashboard schema."""
    return UsageTotals(
        loaded=raw.get("loaded", 0),
        cited=raw.get("referenced", raw.get("cited", 0)),
        helpful=raw.get("helpful", 0),
        harmful=raw.get("harmful", 0),
        success=raw.get("success", 0),
    )


def _build_st_usage_payload_preview(quick: list[str]) -> str:
    """Return a compact prompt payload preview for the analytics UI."""
    lines = [
        "<tool-capabilities>",
        "tools:",
        "- tool: st",
        "  quick:",
    ]
    lines.extend(f"  - {entry}" for entry in quick)
    lines.append("</tool-capabilities>")
    return "\n".join(lines)


def _build_st_usage_summary(memory: StUsageMemory) -> StUsageSummary:
    """Convert st usage memory into the dashboard response model."""
    help_rate = round(memory.help_count / memory.observed, 3) if memory.observed else 0.0
    return StUsageSummary(
        observed_commands=memory.observed,
        help_lookups=memory.help_count,
        help_rate=help_rate,
        quick_entry_count=len(memory.quick),
        quick_entries=[
            StUsageQuickEntryModel(
                command=entry.command,
                description=entry.description,
                source=entry.source,
            )
            for entry in memory.quick_entries
        ],
        command_metrics=[
            StUsageCommandMetricModel(
                command_key=metric.command_key,
                uses=metric.uses,
                help_lookups=metric.help_lookups,
                injected_example=metric.injected_example,
                last_seen=metric.last_seen,
            )
            for metric in memory.command_metrics
        ],
        payload_preview=_build_st_usage_payload_preview(memory.quick),
        cache_ttl_seconds=memory.cache_ttl_seconds,
        lookback=memory.lookback,
        generated_at=memory.generated_at.isoformat(),
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
    success_count = sum(1 for r in records if r.get("task_succeeded") is True)
    fail_count = sum(1 for r in records if r.get("task_succeeded") is False)
    unknown_count = sum(1 for r in records if r.get("task_succeeded") is None)
    known_count = success_count + fail_count
    total = known_count + unknown_count
    return OutcomeSummary(
        success_count=success_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        known_count=known_count,
        coverage_rate=known_count / total if total > 0 else 0.0,
        success_rate=success_count / known_count if known_count > 0 else 0.0,
    )


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    """Read a field from a row snapshot or ORM object."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _accumulate_injection_record(
    record: Any,
    period: str,
    variant_data: dict[str, dict[str, Any]],
    period_data: dict[str, dict[str, Any]],
    normalized: list[dict[str, Any]],
) -> None:
    """Accumulate one injection record into variant and period buckets."""
    loaded = _record_value(record, "memories_loaded") or []
    cited = _record_value(record, "memories_cited") or []
    task_succeeded = _record_value(record, "task_succeeded")
    normalized.append({"task_succeeded": task_succeeded})

    variant = _record_value(record, "variant") or "BASELINE"
    vb = variant_data[variant]
    vb["count"] += 1
    if task_succeeded is True:
        vb["success"] += 1
    elif task_succeeded is False:
        vb["fail"] += 1
    else:
        vb["unknown"] += 1
    vb["latency_sum"] += _record_value(record, "injection_latency_ms") or 0
    vb["tokens_sum"] += _record_value(record, "total_tokens") or 0
    vb["loaded_sum"] += len(loaded)
    vb["cited_sum"] += len(cited)

    period_key = _format_period_key(_record_value(record, "created_at"), period)
    pb = period_data[period_key]
    pb["count"] += 1
    if task_succeeded is True:
        pb["success"] += 1
        pb["known"] += 1
    elif task_succeeded is False:
        pb["known"] += 1
    pb["loaded"] += len(loaded)
    pb["cited"] += len(cited)


def _build_variant_metrics_list(variant_data: dict[str, dict[str, Any]]) -> list[VariantMetrics]:
    """Build sorted VariantMetrics list from accumulated variant buckets."""
    result = []
    for variant, data in sorted(variant_data.items()):
        count = data["count"]
        known = data["success"] + data["fail"]
        result.append(
            VariantMetrics(
                variant=variant,
                injection_count=count,
                success_count=data["success"],
                fail_count=data["fail"],
                unknown_count=data["unknown"],
                success_rate=round(data["success"] / known if known > 0 else 0.0, 3),
                citation_rate=round(
                    data["cited_sum"] / data["loaded_sum"] if data["loaded_sum"] > 0 else 0.0, 3
                ),
                avg_latency_ms=round(data["latency_sum"] / count if count > 0 else 0.0, 1),
                avg_tokens=round(data["tokens_sum"] / count if count > 0 else 0.0, 1),
            )
        )
    return result


def _build_period_metrics_list(period_data: dict[str, dict[str, Any]]) -> list[TimePeriodMetrics]:
    """Build sorted TimePeriodMetrics list from accumulated period buckets."""
    return [
        TimePeriodMetrics(
            period=period_key,
            injection_count=data["count"],
            avg_success_rate=round(
                data["success"] / data["known"] if data["known"] > 0 else 0.0, 3
            ),
            avg_citation_rate=round(
                data["cited"] / data["loaded"] if data["loaded"] > 0 else 0.0, 3
            ),
        )
        for period_key, data in sorted(period_data.items())
    ]


async def _fetch_injection_records(
    start_date: datetime,
    end_date: datetime,
    variant_filter: str | None,
    project_id_filter: str | None,
) -> list[Any]:
    """Execute the injection metrics query and return detached-safe snapshots."""
    query = select(
        MemoryInjectionMetric.memories_loaded,
        MemoryInjectionMetric.memories_cited,
        MemoryInjectionMetric.task_succeeded,
        MemoryInjectionMetric.variant,
        MemoryInjectionMetric.injection_latency_ms,
        MemoryInjectionMetric.total_tokens,
        MemoryInjectionMetric.created_at,
    ).where(
        MemoryInjectionMetric.created_at >= start_date,
        MemoryInjectionMetric.created_at <= end_date,
    )
    if variant_filter:
        query = query.where(MemoryInjectionMetric.variant == variant_filter)
    if project_id_filter:
        query = query.where(MemoryInjectionMetric.project_id == project_id_filter)
    async with async_session() as session:
        result = await session.execute(query)
        return [dict(row) for row in result.mappings().all()]


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
    raw_records = await _fetch_injection_records(
        start_date, end_date, variant_filter, project_id_filter
    )

    variant_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "success": 0, "fail": 0, "unknown": 0,
                 "latency_sum": 0, "tokens_sum": 0, "loaded_sum": 0, "cited_sum": 0}
    )
    period_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "success": 0, "known": 0, "loaded": 0, "cited": 0}
    )
    normalized_records: list[dict[str, Any]] = []

    for record in raw_records:
        _accumulate_injection_record(record, period, variant_data, period_data, normalized_records)

    by_variant = _build_variant_metrics_list(variant_data)
    by_period = _build_period_metrics_list(period_data)
    outcomes = _build_outcome_summary(normalized_records)
    total_loaded = sum(d["loaded_sum"] for d in variant_data.values())
    total_cited = sum(d["cited_sum"] for d in variant_data.values())

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


async def get_memory_dashboard(
    *,
    group_id: str | None = None,
    lookback_delta: timedelta,
    lookback_label: str,
    top_memories_sort_by: str = "utility_score",
    top_memories_limit: int = 8,
) -> MemoryAnalyticsDashboard:
    """Return the explicit analytics dashboard payload for the memory page."""
    period = "hour" if lookback_delta <= timedelta(days=1) else "day"
    project_id_filter = _project_id_filter_from_group_id(group_id)

    tier_dist = await get_tier_distribution(group_id)
    scope_dist = await get_scope_distribution(group_id)
    state_usage_totals = _normalize_usage_totals(await get_usage_aggregates(group_id))
    avg_utility = await get_avg_utility_score(group_id)
    avg_lifecycle = await get_avg_lifecycle_score(group_id)
    lifecycle_tiers = await get_lifecycle_by_tier(group_id)
    top_memories = await get_top_memories_query(group_id, top_memories_sort_by, top_memories_limit)

    activity_usage_totals = _normalize_usage_totals(await get_recent_usage_totals(lookback_delta))
    injection_metrics = await get_injection_metrics_summary(
        lookback_delta,
        period=period,
        project_id_filter=project_id_filter,
    )
    utilization: MemoryUtilizationMetrics = await get_memory_utilization_summary(
        lookback_delta,
        project_id_filter=project_id_filter,
    )
    st_usage = _build_st_usage_summary(
        await get_recent_st_usage_memory(
            project_id=project_id_filter,
            task_type=None,
        )
    )
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
        utilization=utilization,
        st_usage=st_usage,
        tier_changes=tier_changes,
    )
    return MemoryAnalyticsDashboard(state=state, activity=activity)
