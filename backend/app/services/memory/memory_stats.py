"""
Statistics and metrics operations for memory service.

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

logger = logging.getLogger(__name__)


async def get_scope_stats(driver: Any) -> list[MemoryScopeCount]:
    """
    Get episode counts by scope.

    Args:
        driver: Neo4j driver instance

    Returns:
        List of scopes with their episode counts
    """
    # Query for distinct group_ids and counts
    query = """
    MATCH (e:Episodic)
    RETURN e.group_id AS group_id, count(e) AS count
    ORDER BY count DESC
    """

    try:
        records, _, _ = await driver.execute_query(query)
        # Parse group_ids to extract scopes
        scope_counts: dict[MemoryScope, int] = {}
        for record in records:
            group_id = record["group_id"] or "global"
            count = record["count"]

            # Parse scope from group_id (format: "global" or "scope-id")
            # build_group_id() uses dashes: "project-{id}"
            if group_id == "global":
                scope = MemoryScope.GLOBAL
            elif group_id.startswith("project-"):
                scope = MemoryScope.PROJECT
            else:
                # Legacy or unknown group_ids default to GLOBAL
                scope = MemoryScope.GLOBAL

            scope_counts[scope] = scope_counts.get(scope, 0) + count

        return [
            MemoryScopeCount(scope=scope, count=count)
            for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
        ]
    except Exception as e:
        logger.error("Failed to get scope stats: %s", e)
        return []


async def get_stats(
    driver: Any,
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
) -> MemoryStats:
    """
    Get memory statistics for dashboard KPIs.

    Returns total count, breakdown by category and scope, and last updated time.
    Uses injection_tier field as source of truth (matches context injection).

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to get stats for
        scope: Memory scope
        scope_id: Scope identifier

    Returns:
        MemoryStats with counts and breakdowns
    """
    # Query stats directly from Neo4j using injection_tier field
    # This is the source of truth, matching context_injector.get_episodes_by_tier()
    # Filter by vector_indexed to match what's actually injectable
    # (episodes with vector_indexed=false are excluded from injection)
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE COALESCE(e.vector_indexed, true) = true
    RETURN e.injection_tier AS tier, count(e) AS count, max(e.created_at) AS last_updated
    ORDER BY count DESC
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            group_id=group_id,
        )

        category_counts: dict[MemoryCategory, int] = {}
        total = 0
        last_updated: datetime | None = None

        for rec in records:
            tier = rec["tier"]
            count = rec["count"]
            rec_last = rec["last_updated"]

            # Convert Neo4j DateTime to Python datetime
            if rec_last is not None and hasattr(rec_last, "to_native"):
                rec_last = rec_last.to_native()

            # Track most recent
            if rec_last and (last_updated is None or rec_last > last_updated):
                last_updated = rec_last

            total += count

            # Map tier string to MemoryCategory
            if tier == "mandate":
                category_counts[MemoryCategory.MANDATE] = count
            elif tier == "guardrail":
                category_counts[MemoryCategory.GUARDRAIL] = count
            elif tier == "reference":
                category_counts[MemoryCategory.REFERENCE] = count
            # Episodes without injection_tier are counted but not categorized

        # Get scope stats
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
        # Fallback to empty stats on error
        return MemoryStats(
            total=0,
            by_category=[],
            by_scope=[],
            last_updated=None,
            scope=scope,
            scope_id=scope_id,
        )
