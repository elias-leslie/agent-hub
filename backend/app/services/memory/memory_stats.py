"""Statistics and metrics operations for memory service."""

import logging
from typing import Any

from .memory_models import (
    MemoryCategory,
    MemoryCategoryCount,
    MemoryScope,
    MemoryScopeCount,
    MemoryStats,
)
from .repository import get_memory_repository

logger = logging.getLogger(__name__)

_TIER_TO_CATEGORY = {
    "mandate": MemoryCategory.MANDATE,
    "guardrail": MemoryCategory.GUARDRAIL,
    "reference": MemoryCategory.REFERENCE,
    "archive": MemoryCategory.ARCHIVE,
}


def _parse_scope(scope_str: str | None) -> MemoryScope:
    """Map scope string to MemoryScope with compatibility for legacy `project:<id>` values."""
    if scope_str and scope_str.startswith("project:"):
        return MemoryScope.PROJECT
    try:
        return MemoryScope(scope_str or MemoryScope.GLOBAL.value)
    except ValueError:
        return MemoryScope.GLOBAL


async def get_scope_stats(driver: Any = None) -> list[MemoryScopeCount]:
    """Get episode counts by scope.

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
    """
    del driver
    repo = get_memory_repository()
    try:
        stats = await repo.get_stats()
        by_scope = stats.get("by_scope", [])

        scope_counts: dict[MemoryScope, int] = {}
        for entry in by_scope:
            scope = _parse_scope(entry.get("scope"))
            scope_counts[scope] = scope_counts.get(scope, 0) + entry.get("count", 0)

        return [
            MemoryScopeCount(scope=scope, count=count)
            for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
        ]
    except Exception as e:
        logger.error("Failed to get scope stats: %s", e)
        return []


async def get_stats(
    group_id: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    driver: Any = None,
) -> MemoryStats:
    """Get memory statistics for dashboard KPIs.

    Returns total count, breakdown by category and scope, and last updated time.

    Args:
        group_id: Group ID for filtering (None = all groups)
        scope: Memory scope for the response
        scope_id: Scope identifier for the response
        driver: Unused (kept for backward compatibility). Pass None.
    """
    del driver
    repo = get_memory_repository()

    try:
        stats = await repo.get_stats(group_id=group_id)

        # Map by_category from tier names to MemoryCategory
        category_counts: list[MemoryCategoryCount] = []
        for entry in stats.get("by_category", []):
            cat_name = entry.get("category", "")
            category = _TIER_TO_CATEGORY.get(cat_name)
            if category is not None:
                category_counts.append(
                    MemoryCategoryCount(category=category, count=entry.get("count", 0))
                )

        # Sort by count descending
        category_counts.sort(key=lambda x: x.count, reverse=True)

        # Get scope stats
        scope_stats = await get_scope_stats()

        return MemoryStats(
            total=stats.get("total", 0),
            by_category=category_counts,
            by_scope=scope_stats,
            last_updated=stats.get("last_updated"),
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
