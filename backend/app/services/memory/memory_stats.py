"""Statistics and metrics operations for memory service.

Handles statistics queries for dashboard KPIs, scope counts, and category breakdowns.
"""

import logging
from datetime import datetime
from typing import Any

from .memory_models import (
    MemoryCategory,
    MemoryCategoryCount,
    MemoryScope,
    MemoryScopeCount,
    MemoryStats,
)
from .query_builders import convert_neo4j_datetime

logger = logging.getLogger(__name__)

_STATS_QUERY_FILTERED = """
MATCH (e:Episodic {group_id: $group_id})
WHERE COALESCE(e.vector_indexed, true) = true
RETURN e.injection_tier AS tier, count(e) AS count, max(e.created_at) AS last_updated
ORDER BY count DESC
"""

_STATS_QUERY_ALL = """
MATCH (e:Episodic)
WHERE COALESCE(e.vector_indexed, true) = true
RETURN e.injection_tier AS tier, count(e) AS count, max(e.created_at) AS last_updated
ORDER BY count DESC
"""

_TIER_TO_CATEGORY = {
    "mandate": MemoryCategory.MANDATE,
    "guardrail": MemoryCategory.GUARDRAIL,
    "reference": MemoryCategory.REFERENCE,
}

_SCOPE_QUERY = """
MATCH (e:Episodic)
RETURN e.group_id AS group_id, count(e) AS count
ORDER BY count DESC
"""


def _build_stats_query(group_id: str | None) -> tuple[str, dict[str, Any]]:
    """Return (query, params) for the stats query based on group_id."""
    if group_id:
        return _STATS_QUERY_FILTERED, {"group_id": group_id}
    return _STATS_QUERY_ALL, {}


def _group_id_to_scope(group_id: str) -> MemoryScope:
    """Map a group_id string to a MemoryScope enum value."""
    if group_id.startswith("project-"):
        return MemoryScope.PROJECT
    return MemoryScope.GLOBAL


def _process_stats_records(
    records: list[Any],
) -> tuple[dict[MemoryCategory, int], int, datetime | None]:
    """Parse query records into category counts, total, and last_updated."""
    category_counts: dict[MemoryCategory, int] = {}
    total = 0
    last_updated: datetime | None = None

    for rec in records:
        count = rec["count"]
        rec_last = convert_neo4j_datetime(rec["last_updated"])

        if rec_last and (last_updated is None or rec_last > last_updated):
            last_updated = rec_last

        total += count

        category = _TIER_TO_CATEGORY.get(rec["tier"])
        if category is not None:
            category_counts[category] = count

    return category_counts, total, last_updated


async def get_scope_stats(driver: Any) -> list[MemoryScopeCount]:
    """Get episode counts by scope."""
    try:
        records, _, _ = await driver.execute_query(_SCOPE_QUERY)
        scope_counts: dict[MemoryScope, int] = {}
        for record in records:
            group_id = record["group_id"] or "global"
            scope = _group_id_to_scope(group_id)
            scope_counts[scope] = scope_counts.get(scope, 0) + record["count"]

        return [
            MemoryScopeCount(scope=scope, count=count)
            for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
        ]
    except Exception as e:
        logger.error("Failed to get scope stats: %s", e)
        return []


async def get_stats(
    driver: Any,
    group_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
) -> MemoryStats:
    """Get memory statistics for dashboard KPIs.

    Returns total count, breakdown by category and scope, and last updated time.
    Uses injection_tier as source of truth (matches context injection).
    """
    query, params = _build_stats_query(group_id)

    try:
        records, _, _ = await driver.execute_query(query, **params)
        category_counts, total, last_updated = _process_stats_records(records)
        scope_stats = await get_scope_stats(driver)

        return MemoryStats(
            total=total,
            by_category=[
                MemoryCategoryCount(category=cat, count=count)
                for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            by_scope=scope_stats,
            last_updated=last_updated,
            scope=scope,
            scope_id=scope_id,
        )

    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        return MemoryStats(
            total=0,
            by_category=[],
            by_scope=[],
            last_updated=None,
            scope=scope,
            scope_id=scope_id,
        )
