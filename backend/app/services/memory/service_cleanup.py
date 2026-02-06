"""Cleanup operations for memory service."""

from __future__ import annotations

from typing import Any

from .memory_queries import (
    cleanup_orphaned_edges,
    cleanup_orphaned_entities,
    cleanup_stale_memories,
    consolidate_duplicate_entities,
)


async def cleanup_orphaned(driver: Any, group_id: str) -> dict[str, Any]:
    """
    Run all orphaned cleanup operations: edges, entities, and duplicate consolidation.

    Args:
        driver: Neo4j driver
        group_id: Group ID for filtering

    Returns:
        Combined results from all cleanup operations
    """
    edge_result = await cleanup_orphaned_edges(driver, group_id)
    entity_result = await cleanup_orphaned_entities(driver, group_id)
    dedup_result = await consolidate_duplicate_entities(driver, group_id)

    return {
        "edges_updated": edge_result.get("edges_updated", 0),
        "edges_deleted": edge_result.get("edges_deleted", 0),
        "stale_refs_removed": edge_result.get("stale_refs_removed", 0),
        "entities_deleted": entity_result.get("entities_deleted", 0),
        "duplicates_merged": dedup_result.get("entities_merged", 0),
    }


async def cleanup_stale(driver: Any, group_id: str, ttl_days: int) -> dict[str, Any]:
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
