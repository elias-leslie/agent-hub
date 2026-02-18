"""Database query functions for memory analytics."""

import logging
from collections import defaultdict
from datetime import datetime

from neo4j import AsyncDriver

from .analytics_models import DailyTrend, ScopeDistribution, TierDistribution, TopMemory

logger = logging.getLogger(__name__)

ALLOWED_SORT_FIELDS = {"utility_score", "referenced_count", "success_count", "loaded_count"}


async def get_tier_distribution(
    driver: AsyncDriver,
    group_id: str | None,
) -> list[TierDistribution]:
    """Get distribution of memories across injection tiers."""
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


async def get_scope_distribution(
    driver: AsyncDriver,
    group_id: str | None,
) -> list[ScopeDistribution]:
    """Get distribution of memories across scopes (global/project)."""
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


async def get_usage_aggregates(
    driver: AsyncDriver,
    group_id: str | None,
) -> dict[str, int]:
    """Get aggregate usage metrics for memories."""
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

    if not records:
        return {"loaded": 0, "referenced": 0, "helpful": 0, "harmful": 0, "success": 0}

    r = records[0]
    return {
        "loaded": int(r["loaded"]),
        "referenced": int(r["referenced"]),
        "helpful": int(r["helpful"]),
        "harmful": int(r["harmful"]),
        "success": int(r["success"]),
    }


async def get_daily_trend(
    driver: AsyncDriver,
    group_id: str | None,
    cutoff: datetime,
) -> list[DailyTrend]:
    """Get daily trend of memory creation since cutoff date."""
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


async def get_avg_utility_score(
    driver: AsyncDriver,
    group_id: str | None,
) -> float:
    """Get average utility score of memories with valid scores."""
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


async def get_top_memories_query(
    driver: AsyncDriver,
    group_id: str | None,
    sort_by: str,
    limit: int,
) -> list[TopMemory]:
    """Get top performing memories sorted by specified field."""
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "utility_score"

    where_clause = "WHERE COALESCE(e.vector_indexed, true) = true"
    params: dict[str, str | int] = {"limit": limit}

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

    records, _, _ = await driver.execute_query(query, parameters_=params)  # ty: ignore[no-matching-overload]

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
