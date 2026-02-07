"""
Query functions for Episodic node properties.

Provides functions to retrieve:
- Episode properties (injection_tier, pinned, auto_inject, etc.)
- Triggered references by task_type
- Triggered references by subtask phase
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver

from app.services.memory.neo4j_queries import execute_episode_query

logger = logging.getLogger(__name__)


async def get_episode_properties(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> dict[str, Any] | None:
    """
    Get all custom properties for an Episodic node.

    Returns injection_tier, pinned, auto_inject, display_order, trigger_task_types, trigger_phases, summary, and usage stats.

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
           COALESCE(e.trigger_phases, []) AS trigger_phases,
           e.summary AS summary,
           COALESCE(e.tags, []) AS tags,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.helpful_count, 0) AS helpful_count,
           COALESCE(e.harmful_count, 0) AS harmful_count
    """

    try:
        records = await execute_episode_query(
            query, {"uuid": episode_uuid}, driver, "get properties"
        )
        return records[0] if records else None
    except Exception as e:
        logger.error("Failed to get properties for %s: %s", episode_uuid[:8], e)
        return None


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
            query,
            {"task_type": task_type, "group_id": group_id},
            driver,
            "get triggered references",
        )
    except Exception as e:
        logger.error("Failed to get triggered references for task_type=%s: %s", task_type, e)
        return []


async def get_phase_triggered_references(
    phase: str,
    group_id: str = "global",
    driver: AsyncDriver | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference episodes that are triggered by a specific subtask phase.

    Returns reference-tier episodes where the phase is in trigger_phases.
    Used for context-aware reference injection based on subtask phase.

    Args:
        phase: The phase to match against trigger_phases (e.g., backend, frontend, database)
        group_id: Group ID to filter episodes (default: global)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        List of episode dicts with uuid, content, name, trigger_phases
    """
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = 'reference'
      AND e.trigger_phases IS NOT NULL
      AND $phase IN e.trigger_phases
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.trigger_phases AS trigger_phases,
           COALESCE(e.display_order, 50) AS display_order
    ORDER BY COALESCE(e.display_order, 50) ASC, e.created_at DESC
    """

    try:
        return await execute_episode_query(
            query,
            {"phase": phase, "group_id": group_id},
            driver,
            "get phase triggered references",
        )
    except Exception as e:
        logger.error("Failed to get phase triggered references for phase=%s: %s", phase, e)
        return []


async def get_episode_tags(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> list[str]:
    """
    Get tags for an Episodic node.

    Args:
        episode_uuid: UUID of the episode to query
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        List of tag strings (empty if episode not found or has no tags)
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    RETURN COALESCE(e.tags, []) AS tags
    """
    try:
        records = await execute_episode_query(
            query, {"uuid": episode_uuid}, driver, "get tags"
        )
        return records[0]["tags"] if records else []
    except Exception as e:
        logger.error("Failed to get tags for %s: %s", episode_uuid[:8], e)
        return []


async def get_all_distinct_tags(
    group_id: str = "global",
    driver: AsyncDriver | None = None,
) -> list[str]:
    """
    Get all distinct tags across all episodes in a group.

    Args:
        group_id: Group ID to filter episodes
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        Sorted list of distinct tag strings
    """
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.tags IS NOT NULL
    UNWIND e.tags AS tag
    RETURN DISTINCT tag
    ORDER BY tag
    """
    try:
        records = await execute_episode_query(
            query, {"group_id": group_id}, driver, "get distinct tags"
        )
        return [r["tag"] for r in records]
    except Exception as e:
        logger.error("Failed to get distinct tags: %s", e)
        return []


async def get_episodes_by_tags(
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    group_id: str = "global",
    driver: AsyncDriver | None = None,
) -> list[dict[str, Any]]:
    """
    Get episodes filtered by include/exclude tags.

    Args:
        include_tags: Episode must have at least one of these tags (empty/None = no filter)
        exclude_tags: Episode must NOT have any of these tags (empty/None = no filter)
        group_id: Group ID to filter episodes
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        List of episode dicts with uuid, content, name, tags
    """
    conditions = ["e.group_id = $group_id"]
    params: dict[str, Any] = {"group_id": group_id}

    if include_tags:
        conditions.append("ANY(t IN COALESCE(e.tags, []) WHERE t IN $include_tags)")
        params["include_tags"] = include_tags

    if exclude_tags:
        conditions.append("NONE(t IN COALESCE(e.tags, []) WHERE t IN $exclude_tags)")
        params["exclude_tags"] = exclude_tags

    where_clause = " AND ".join(conditions)
    query = f"""
    MATCH (e:Episodic)
    WHERE {where_clause}
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           COALESCE(e.tags, []) AS tags,
           e.injection_tier AS injection_tier
    ORDER BY e.created_at DESC
    """

    try:
        return await execute_episode_query(query, params, driver, "filter by tags")
    except Exception as e:
        logger.error("Failed to filter episodes by tags: %s", e)
        return []
