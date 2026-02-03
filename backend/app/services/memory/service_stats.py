"""Statistics operations for memory service."""

from typing import Any

from .memory_models import MemoryScope, MemoryScopeCount, MemoryStats
from .memory_stats import get_scope_stats, get_stats


async def get_all_scope_stats(driver: Any) -> list[MemoryScopeCount]:
    """Get episode counts by scope."""
    return await get_scope_stats(driver)


async def get_memory_stats(
    driver: Any,
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
) -> MemoryStats:
    """Get memory statistics for dashboard KPIs."""
    return await get_stats(driver, group_id, scope, scope_id)
