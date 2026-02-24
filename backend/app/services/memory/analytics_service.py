"""Memory analytics service providing usage metrics and insights."""

import logging
from datetime import UTC, datetime, timedelta

# Re-export models for backward compatibility
from .analytics_models import (
    DailyTrend,
    MemoryAnalytics,
    ScopeDistribution,
    TierDistribution,
    TopMemory,
)
from .analytics_queries import (
    get_avg_utility_score,
    get_daily_trend,
    get_scope_distribution,
    get_tier_distribution,
    get_top_memories_query,
    get_usage_aggregates,
)

logger = logging.getLogger(__name__)


def _compute_usage_rates(
    usage: dict[str, int],
) -> tuple[int, int, int, int, int, float, float]:
    """Extract and compute usage counts and derived rates from raw usage aggregates.

    Returns:
        Tuple of (total_loaded, total_cited, total_helpful, total_harmful,
                  total_success, citation_rate, success_rate)
    """
    total_loaded = usage.get("loaded", 0)
    total_cited = usage.get("referenced", 0)
    total_helpful = usage.get("helpful", 0)
    total_harmful = usage.get("harmful", 0)
    total_success = usage.get("success", 0)
    citation_rate = total_cited / total_loaded if total_loaded > 0 else 0.0
    success_rate = total_success / total_loaded if total_loaded > 0 else 0.0
    return (
        total_loaded,
        total_cited,
        total_helpful,
        total_harmful,
        total_success,
        citation_rate,
        success_rate,
    )


async def _fetch_analytics_data(
    group_id: str | None,
    cutoff: datetime,
) -> tuple[list[TierDistribution], list[ScopeDistribution], dict[str, int], list[DailyTrend], float]:
    """Fetch all raw analytics data from PostgreSQL.

    Returns:
        Tuple of (tier_dist, scope_dist, usage, trend, avg_utility)
    """
    tier_dist = await get_tier_distribution(group_id)
    scope_dist = await get_scope_distribution(group_id)
    usage = await get_usage_aggregates(group_id)
    trend = await get_daily_trend(group_id, cutoff)
    avg_utility = await get_avg_utility_score(group_id)
    return tier_dist, scope_dist, usage, trend, avg_utility


async def get_memory_analytics(
    group_id: str | None = None,
    days: int = 30,
) -> MemoryAnalytics:
    """
    Get comprehensive analytics for memory usage and performance.

    Args:
        group_id: Filter by group (None for all groups)
        days: Number of days to include in trend analysis

    Returns:
        MemoryAnalytics with aggregated metrics and distributions
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    tier_dist, scope_dist, usage, trend, avg_utility = await _fetch_analytics_data(
        group_id, cutoff
    )

    total = sum(t.count for t in tier_dist)
    (
        total_loaded,
        total_cited,
        total_helpful,
        total_harmful,
        total_success,
        citation_rate,
        success_rate,
    ) = _compute_usage_rates(usage)

    return MemoryAnalytics(
        total_episodes=total,
        tier_distribution=tier_dist,
        scope_distribution=scope_dist,
        total_loaded=total_loaded,
        total_cited=total_cited,
        total_helpful=total_helpful,
        total_harmful=total_harmful,
        total_success=total_success,
        citation_rate=round(citation_rate, 3),
        success_rate=round(success_rate, 3),
        daily_trend=trend,
        avg_utility_score=round(avg_utility, 3),
    )


async def get_top_memories(
    group_id: str | None = None,
    sort_by: str = "utility_score",
    limit: int = 8,
) -> list[TopMemory]:
    """
    Get top performing memories sorted by specified metric.

    Args:
        group_id: Filter by group (None for all groups)
        sort_by: Sort field (utility_score, referenced_count, loaded_count, helpful_count)
        limit: Maximum number of results (1-50)

    Returns:
        List of TopMemory objects sorted by the specified field
    """
    return await get_top_memories_query(group_id, sort_by, limit)
