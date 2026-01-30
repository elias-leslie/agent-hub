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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver

from app.services.memory.neo4j_queries import (
    execute_batch_update,
    execute_episode_query,
    execute_episode_update,
)

logger = logging.getLogger(__name__)


async def set_episode_injection_tier(
    episode_uuid: str,
    injection_tier: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set injection_tier property on an Episodic node.

    Valid tiers: mandate, guardrail, reference, pending_review

    Args:
        episode_uuid: UUID of the episode to update
        injection_tier: Tier value
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.injection_tier = $tier
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "tier": injection_tier},
        episode_uuid,
        driver,
        f"set injection_tier={injection_tier}",
    )


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


async def set_episode_pinned(
    episode_uuid: str,
    pinned: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set pinned property on an Episodic node.

    Pinned episodes are never automatically demoted by tier_optimizer.

    Args:
        episode_uuid: UUID of the episode to update
        pinned: Whether to pin the episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.pinned = $pinned
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query, {"uuid": episode_uuid, "pinned": pinned}, episode_uuid, driver, f"set pinned={pinned}"
    )


async def set_episode_auto_inject(
    episode_uuid: str,
    auto_inject: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set auto_inject property on an Episodic node.

    For reference-tier episodes, auto_inject=true makes them behave like
    mandates/guardrails - injected in every session regardless of query.

    Args:
        episode_uuid: UUID of the episode to update
        auto_inject: Whether to auto-inject the episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.auto_inject = $auto_inject
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "auto_inject": auto_inject},
        episode_uuid,
        driver,
        f"set auto_inject={auto_inject}",
    )


async def set_episode_display_order(
    episode_uuid: str,
    display_order: int,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set display_order property on an Episodic node.

    Controls injection ordering within the same tier. Lower values = earlier.
    Default is 50. Use 1-10 for high priority, 90-99 for low priority.

    Args:
        episode_uuid: UUID of the episode to update
        display_order: Order value (lower = earlier in injection)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.display_order = $display_order
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "display_order": display_order},
        episode_uuid,
        driver,
        f"set display_order={display_order}",
    )


async def set_episode_trigger_task_types(
    episode_uuid: str,
    trigger_task_types: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set trigger_task_types property on an Episodic node.

    Specifies which task_types should automatically inject this reference episode.

    Args:
        episode_uuid: UUID of the episode to update
        trigger_task_types: List of task_type strings that trigger this episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.trigger_task_types = $trigger_task_types
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "trigger_task_types": trigger_task_types},
        episode_uuid,
        driver,
        f"set trigger_task_types={trigger_task_types}",
    )


async def set_episode_summary(
    episode_uuid: str,
    summary: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set summary property on an Episodic node.

    Summary is a ~20 char action phrase for TOON index format.
    Example: "use dt for tests", "no time estimates", "type all sigs"

    Args:
        episode_uuid: UUID of the episode to update
        summary: Short action phrase (ideally <25 chars)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.summary = $summary
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query, {"uuid": episode_uuid, "summary": summary}, episode_uuid, driver, f"set summary={summary[:20]}"
    )


async def copy_episode_stats(
    source_uuid: str,
    target_uuid: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Copy usage stats from one episode to another.

    Copies loaded_count, referenced_count, helpful_count, harmful_count,
    utility_score, pinned, auto_inject, display_order, summary, and trigger_task_types.
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
        target.trigger_task_types = source.trigger_task_types
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
            "Failed to copy stats: source %s or target %s not found", source_uuid[:8], target_uuid[:8]
        )
        return False
    except Exception as e:
        logger.error("Failed to copy stats from %s to %s: %s", source_uuid[:8], target_uuid[:8], e)
        return False


async def get_episode_properties(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> dict[str, Any] | None:
    """
    Get all custom properties for an Episodic node.

    Returns injection_tier, pinned, auto_inject, display_order, trigger_task_types, summary, and usage stats.

    Args:
        episode_uuid: UUID of the episode to query
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        Dict with properties or None if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    RETURN e.uuid AS uuid,
           e.injection_tier AS injection_tier,
           COALESCE(e.pinned, false) AS pinned,
           COALESCE(e.auto_inject, false) AS auto_inject,
           COALESCE(e.display_order, 50) AS display_order,
           COALESCE(e.trigger_task_types, []) AS trigger_task_types,
           e.summary AS summary,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.helpful_count, 0) AS helpful_count,
           COALESCE(e.harmful_count, 0) AS harmful_count
    """

    try:
        records = await execute_episode_query(query, {"uuid": episode_uuid}, driver, "get properties")
        return records[0] if records else None
    except Exception as e:
        logger.error("Failed to get properties for %s: %s", episode_uuid[:8], e)
        return None


async def batch_update_episode_properties(
    updates: list[dict[str, Any]],
    driver: AsyncDriver | None = None,
) -> dict[str, bool]:
    """
    Batch update properties for multiple episodes in a single query.

    Supports updating: injection_tier, summary, trigger_task_types, pinned, auto_inject, display_order.
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
        e.pinned = COALESCE(update.pinned, e.pinned),
        e.auto_inject = COALESCE(update.auto_inject, e.auto_inject),
        e.display_order = COALESCE(update.display_order, e.display_order)
    RETURN e.uuid AS uuid
    """
    return await execute_batch_update(query, updates, driver, "batch properties update")


async def get_triggered_references(
    task_type: str,
    group_id: str = "global",
    driver: AsyncDriver | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference episodes that are triggered by a specific task_type.

    Returns reference-tier episodes where the task_type is in trigger_task_types.
    Used for context-aware reference injection based on task type.

    Args:
        task_type: The task type to match against trigger_task_types
        group_id: Group ID to filter episodes (default: global)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        List of episode dicts with uuid, content, name, trigger_task_types
    """
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = 'reference'
      AND e.trigger_task_types IS NOT NULL
      AND $task_type IN e.trigger_task_types
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.trigger_task_types AS trigger_task_types,
           COALESCE(e.display_order, 50) AS display_order
    ORDER BY COALESCE(e.display_order, 50) ASC, e.created_at DESC
    """

    try:
        return await execute_episode_query(
            query, {"task_type": task_type, "group_id": group_id}, driver, "get triggered references"
        )
    except Exception as e:
        logger.error("Failed to get triggered references for task_type=%s: %s", task_type, e)
        return []
