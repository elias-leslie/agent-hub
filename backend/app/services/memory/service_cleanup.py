"""Cleanup operations for memory service."""

from typing import Any

from .memory_queries import cleanup_orphaned_edges, cleanup_stale_memories


async def cleanup_orphaned(driver: Any, group_id: str) -> dict[str, Any]:
    """
    Clean up edges with stale episode references.

    Args:
        driver: Neo4j driver
        group_id: Group ID for filtering

    Returns:
        Dict with cleanup results: edges_updated, edges_deleted, stale_refs_removed
    """
    return await cleanup_orphaned_edges(driver, group_id)


async def cleanup_stale(
    driver: Any, group_id: str, ttl_days: int
) -> dict[str, Any]:
    """
    Clean up memories that haven't been accessed within TTL period.

    Args:
        driver: Neo4j driver
        group_id: Group ID for filtering
        ttl_days: Days without access before memory is considered stale

    Returns:
        Dict with cleanup results: deleted count, skipped, and reason
    """
    return await cleanup_stale_memories(driver, group_id, ttl_days)
