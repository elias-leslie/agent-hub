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
