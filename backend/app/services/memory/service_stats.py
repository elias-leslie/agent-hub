"""Statistics operations for memory service.

Uses MemoryRepository (PostgreSQL) instead of Neo4j.
"""

from .memory_models import MemoryScope, MemoryScopeCount, MemoryStats
from .memory_stats import get_scope_stats, get_stats


async def get_all_scope_stats() -> list[MemoryScopeCount]:
    """Get episode counts by scope."""
    return await get_scope_stats()


async def get_memory_stats(
    group_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
) -> MemoryStats:
    """Get memory statistics for dashboard KPIs."""
    return await get_stats(group_id, scope, scope_id)
