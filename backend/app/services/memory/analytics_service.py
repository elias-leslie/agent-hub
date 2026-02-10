import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)


class TierDistribution(BaseModel):
    tier: str
    count: int
    percentage: float


class ScopeDistribution(BaseModel):
    scope: str
    count: int
    percentage: float


class DailyTrend(BaseModel):
    date: str
    count: int


class TopMemory(BaseModel):
    uuid: str
    content: str
    injection_tier: str
    utility_score: float
    loaded_count: int
    referenced_count: int
    success_count: int


class MemoryAnalytics(BaseModel):
    total_episodes: int
    tier_distribution: list[TierDistribution]
    scope_distribution: list[ScopeDistribution]
    total_loaded: int
    total_cited: int
    total_helpful: int
    total_harmful: int
    total_success: int
    citation_rate: float
    success_rate: float
    daily_trend: list[DailyTrend]
    avg_utility_score: float


async def get_memory_analytics(
    group_id: str | None = None,
    days: int = 30,
) -> MemoryAnalytics:
    graphiti = get_graphiti()
    driver = graphiti.driver

    cutoff = datetime.now(UTC) - timedelta(days=days)

    tier_dist = await _get_tier_distribution(driver, group_id)
    scope_dist = await _get_scope_distribution(driver, group_id)
    usage = await _get_usage_aggregates(driver, group_id)
    trend = await _get_daily_trend(driver, group_id, cutoff)
    avg_utility = await _get_avg_utility_score(driver, group_id)

    total = sum(t.count for t in tier_dist)

    total_loaded = usage.get("loaded", 0)
    total_cited = usage.get("referenced", 0)
    total_helpful = usage.get("helpful", 0)
    total_harmful = usage.get("harmful", 0)
    total_success = usage.get("success", 0)
    citation_rate = total_cited / total_loaded if total_loaded > 0 else 0.0
    success_rate = total_success / total_loaded if total_loaded > 0 else 0.0

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


async def _get_tier_distribution(
    driver: Any,
    group_id: str | None,
) -> list[TierDistribution]:
    if group_id:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN COALESCE(e.injection_tier, 'reference') AS tier, count(e) AS count
        ORDER BY count DESC
        """
        records, _, _ = await driver.execute_query(query, group_id=group_id)
    else:
        query = """
        MATCH (e:Episodic)
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN COALESCE(e.injection_tier, 'reference') AS tier, count(e) AS count
        ORDER BY count DESC
        """
        records, _, _ = await driver.execute_query(query)

    total = sum(r["count"] for r in records)
    return [
        TierDistribution(
            tier=r["tier"],
            count=r["count"],
            percentage=round(r["count"] / total * 100, 1) if total > 0 else 0.0,
        )
        for r in records
    ]


async def _get_scope_distribution(
    driver: Any,
    group_id: str | None,
) -> list[ScopeDistribution]:
    if group_id:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN e.group_id AS gid, count(e) AS count
        ORDER BY count DESC
        """
        records, _, _ = await driver.execute_query(query, group_id=group_id)
    else:
        query = """
        MATCH (e:Episodic)
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN e.group_id AS gid, count(e) AS count
        ORDER BY count DESC
        """
        records, _, _ = await driver.execute_query(query)

    scope_counts: dict[str, int] = defaultdict(int)
    for r in records:
        gid = r["gid"] or "global"
        if gid == "global":
            scope_counts["global"] += r["count"]
        elif gid.startswith("project-"):
            scope_counts["project"] += r["count"]
        else:
            scope_counts["global"] += r["count"]

    total = sum(scope_counts.values())
    return [
        ScopeDistribution(
            scope=scope,
            count=count,
            percentage=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
    ]


async def _get_usage_aggregates(
    driver: Any,
    group_id: str | None,
) -> dict[str, int]:
    if group_id:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN
            COALESCE(sum(e.loaded_count), 0) AS loaded,
            COALESCE(sum(e.referenced_count), 0) AS referenced,
            COALESCE(sum(e.helpful_count), 0) AS helpful,
            COALESCE(sum(e.harmful_count), 0) AS harmful,
            COALESCE(sum(e.success_count), 0) AS success
        """
        records, _, _ = await driver.execute_query(query, group_id=group_id)
    else:
        query = """
        MATCH (e:Episodic)
        WHERE COALESCE(e.vector_indexed, true) = true
        RETURN
            COALESCE(sum(e.loaded_count), 0) AS loaded,
            COALESCE(sum(e.referenced_count), 0) AS referenced,
            COALESCE(sum(e.helpful_count), 0) AS helpful,
            COALESCE(sum(e.harmful_count), 0) AS harmful,
            COALESCE(sum(e.success_count), 0) AS success
        """
        records, _, _ = await driver.execute_query(query)

    if records:
        r = records[0]
        return {
            "loaded": int(r["loaded"]),
            "referenced": int(r["referenced"]),
            "helpful": int(r["helpful"]),
            "harmful": int(r["harmful"]),
            "success": int(r["success"]),
        }
    return {"loaded": 0, "referenced": 0, "helpful": 0, "harmful": 0, "success": 0}


async def _get_daily_trend(
    driver: Any,
    group_id: str | None,
    cutoff: datetime,
) -> list[DailyTrend]:
    if group_id:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        WHERE e.created_at >= datetime($cutoff)
          AND COALESCE(e.vector_indexed, true) = true
        WITH date(e.created_at) AS day, count(e) AS count
        RETURN toString(day) AS date, count
        ORDER BY date ASC
        """
        records, _, _ = await driver.execute_query(
            query, group_id=group_id, cutoff=cutoff.isoformat()
        )
    else:
        query = """
        MATCH (e:Episodic)
        WHERE e.created_at >= datetime($cutoff)
          AND COALESCE(e.vector_indexed, true) = true
        WITH date(e.created_at) AS day, count(e) AS count
        RETURN toString(day) AS date, count
        ORDER BY date ASC
        """
        records, _, _ = await driver.execute_query(query, cutoff=cutoff.isoformat())

    return [DailyTrend(date=r["date"], count=r["count"]) for r in records]


async def _get_avg_utility_score(
    driver: Any,
    group_id: str | None,
) -> float:
    if group_id:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        WHERE e.utility_score IS NOT NULL
          AND e.utility_score > 0
          AND COALESCE(e.vector_indexed, true) = true
        RETURN avg(e.utility_score) AS avg_score
        """
        records, _, _ = await driver.execute_query(query, group_id=group_id)
    else:
        query = """
        MATCH (e:Episodic)
        WHERE e.utility_score IS NOT NULL
          AND e.utility_score > 0
          AND COALESCE(e.vector_indexed, true) = true
        RETURN avg(e.utility_score) AS avg_score
        """
        records, _, _ = await driver.execute_query(query)

    if records and records[0]["avg_score"] is not None:
        return float(records[0]["avg_score"])
    return 0.0


_ALLOWED_SORT_FIELDS = {"utility_score", "referenced_count", "success_count", "loaded_count"}


async def get_top_memories(
    group_id: str | None = None,
    sort_by: str = "utility_score",
    limit: int = 8,
) -> list[TopMemory]:
    if sort_by not in _ALLOWED_SORT_FIELDS:
        sort_by = "utility_score"

    graphiti = get_graphiti()
    driver = graphiti.driver

    where_clause = "WHERE COALESCE(e.vector_indexed, true) = true"
    params: dict[str, Any] = {"limit": limit}

    if group_id:
        where_clause = "WHERE e.group_id = $group_id AND COALESCE(e.vector_indexed, true) = true"
        params["group_id"] = group_id

    query = f"""
    MATCH (e:Episodic)
    {where_clause}
    WITH e,
         COALESCE(e.{sort_by}, 0) AS sort_val
    ORDER BY sort_val DESC
    LIMIT $limit
    RETURN
        e.uuid AS uuid,
        left(e.content, 120) AS content,
        COALESCE(e.injection_tier, 'reference') AS injection_tier,
        COALESCE(e.utility_score, 0.0) AS utility_score,
        COALESCE(e.loaded_count, 0) AS loaded_count,
        COALESCE(e.referenced_count, 0) AS referenced_count,
        COALESCE(e.success_count, 0) AS success_count
    """

    records, _, _ = await driver.execute_query(query, **params)

    return [
        TopMemory(
            uuid=str(r["uuid"]),
            content=str(r["content"]),
            injection_tier=str(r["injection_tier"]),
            utility_score=float(r["utility_score"]),
            loaded_count=int(r["loaded_count"]),
            referenced_count=int(r["referenced_count"]),
            success_count=int(r["success_count"]),
        )
        for r in records
    ]
