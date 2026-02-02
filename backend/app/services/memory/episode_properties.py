"""
Episode property management for Graphiti Episodic nodes.

Extends Graphiti's Episodic nodes with custom properties for the memory system:
- injection_tier: mandate/guardrail/reference/pending_review
- pinned: Never auto-demote
- auto_inject: Always inject (for reference tier)
- display_order: Injection ordering within tier
- trigger_task_types: Auto-inject when task_type matches
- summary: Short action phrase for TOON index
- Usage stats: loaded_count, referenced_count, helpful_count, harmful_count

This module provides batch operations, stats management, and re-exports
all individual property setters and query functions for convenience.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver

# Re-export all query functions
from app.services.memory.episode_property_queries import (
    get_episode_properties,
    get_phase_triggered_references,
    get_triggered_references,
)

# Re-export all individual setters
from app.services.memory.episode_property_setters import (
    set_episode_auto_inject,
    set_episode_display_order,
    set_episode_injection_tier,
    set_episode_pinned,
    set_episode_summary,
    set_episode_trigger_phases,
    set_episode_trigger_task_types,
)
from app.services.memory.neo4j_queries import (
    execute_batch_update,
    execute_episode_query,
    execute_episode_update,
)

logger = logging.getLogger(__name__)

# Make re-exported functions available for star imports
__all__ = [
    "batch_set_episode_injection_tier",
    "batch_update_episode_properties",
    "copy_episode_stats",
    "get_episode_properties",
    "get_phase_triggered_references",
    "get_triggered_references",
    "init_episode_usage_properties",
    "set_episode_auto_inject",
    "set_episode_display_order",
    "set_episode_injection_tier",
    "set_episode_pinned",
    "set_episode_summary",
    "set_episode_trigger_phases",
    "set_episode_trigger_task_types",
]


async def batch_set_episode_injection_tier(
    updates: list[tuple[str, str]],
    driver: AsyncDriver | None = None,
) -> dict[str, bool]:
    """
    Batch update injection_tier for multiple episodes in a single query.

    Args:
        updates: List of (episode_uuid, injection_tier) tuples
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        Dict mapping episode_uuid to success status (True if updated)
    """
    query = """
    UNWIND $updates AS update
    MATCH (e:Episodic {uuid: update.uuid})
    SET e.injection_tier = update.tier
    RETURN e.uuid AS uuid
    """
    update_params = [{"uuid": uuid, "tier": tier} for uuid, tier in updates]
    return await execute_batch_update(query, update_params, driver, "batch tier update")


async def batch_update_episode_properties(
    updates: list[dict[str, Any]],
    driver: AsyncDriver | None = None,
) -> dict[str, bool]:
    """
    Batch update properties for multiple episodes in a single query.

    Supports updating: injection_tier, summary, trigger_task_types, trigger_phases, pinned, auto_inject, display_order.
    Only provided fields are updated (partial update).

    Args:
        updates: List of dicts with 'uuid' and optional property fields
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        Dict mapping episode_uuid to success status (True if updated)
    """
    query = """
    UNWIND $updates AS update
    MATCH (e:Episodic {uuid: update.uuid})
    SET e.injection_tier = COALESCE(update.injection_tier, e.injection_tier),
        e.summary = COALESCE(update.summary, e.summary),
        e.trigger_task_types = COALESCE(update.trigger_task_types, e.trigger_task_types),
        e.trigger_phases = COALESCE(update.trigger_phases, e.trigger_phases),
        e.pinned = COALESCE(update.pinned, e.pinned),
        e.auto_inject = COALESCE(update.auto_inject, e.auto_inject),
        e.display_order = COALESCE(update.display_order, e.display_order)
    RETURN e.uuid AS uuid
    """
    return await execute_batch_update(query, updates, driver, "batch properties update")


async def init_episode_usage_properties(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Initialize usage tracking properties on an Episodic node.

    Sets loaded_count and referenced_count to 0 for new episodes.

    Args:
        episode_uuid: UUID of the episode to initialize
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.loaded_count = 0, e.referenced_count = 0
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query, {"uuid": episode_uuid}, episode_uuid, driver, "init usage properties"
    )


async def copy_episode_stats(
    source_uuid: str,
    target_uuid: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Copy usage stats from one episode to another.

    Copies loaded_count, referenced_count, helpful_count, harmful_count,
    utility_score, pinned, auto_inject, display_order, summary, trigger_task_types, and trigger_phases.
    Used when editing episodes (delete + recreate) to preserve feedback data.

    Args:
        source_uuid: UUID of the episode to copy stats from
        target_uuid: UUID of the episode to copy stats to
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if copied, False if source or target not found
    """
    query = """
    MATCH (source:Episodic {uuid: $source_uuid})
    MATCH (target:Episodic {uuid: $target_uuid})
    SET target.loaded_count = COALESCE(source.loaded_count, 0),
        target.referenced_count = COALESCE(source.referenced_count, 0),
        target.helpful_count = COALESCE(source.helpful_count, 0),
        target.harmful_count = COALESCE(source.harmful_count, 0),
        target.utility_score = source.utility_score,
        target.pinned = COALESCE(source.pinned, false),
        target.auto_inject = COALESCE(source.auto_inject, false),
        target.display_order = COALESCE(source.display_order, 50),
        target.summary = source.summary,
        target.trigger_task_types = source.trigger_task_types,
        target.trigger_phases = source.trigger_phases
    RETURN target.uuid AS uuid
    """

    try:
        records = await execute_episode_query(
            query, {"source_uuid": source_uuid, "target_uuid": target_uuid}, driver, "copy stats"
        )
        if records:
            logger.debug("Copied stats from %s to %s", source_uuid[:8], target_uuid[:8])
            return True
        logger.warning(
            "Failed to copy stats: source %s or target %s not found",
            source_uuid[:8],
            target_uuid[:8],
        )
        return False
    except Exception as e:
        logger.error("Failed to copy stats from %s to %s: %s", source_uuid[:8], target_uuid[:8], e)
        return False
