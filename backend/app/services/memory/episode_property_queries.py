"""
Query functions for memory record properties.

Provides functions to retrieve:
- Memory properties (injection_tier, pinned, auto_inject, etc.)
- Triggered references by task_type
- Triggered references by subtask phase
- Tags (per-memory and distinct across group)
- Filtering by tags

All functions delegate to MemoryRepository.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.memory.repository import MemoryRepository, get_memory_repository

logger = logging.getLogger(__name__)


async def get_episode_properties(
    episode_uuid: str,
) -> dict[str, Any] | None:
    """
    Get all custom properties for a memory record.

    Returns injection_tier, pinned, auto_inject, display_order, trigger_task_types,
    trigger_phases, summary, and usage stats.

    Args:
        episode_uuid: UUID of the memory to query

    Returns:
        Dict with properties or None if memory not found
    """
    repo = get_memory_repository()
    try:
        return await repo.get_as_dict(episode_uuid)
    except Exception as e:
        logger.error("Failed to get properties for %s: %s", episode_uuid[:8], e)
        return None


async def get_triggered_references(
    task_type: str,
    group_id: str = "global",
) -> list[dict[str, Any]]:
    """
    Get reference memories that are triggered by a specific task_type.

    Returns reference-tier memories where the task_type is in trigger_task_types.
    Used for context-aware reference injection based on task type.

    Args:
        task_type: The task type to match against trigger_task_types
        group_id: Group ID to filter memories (default: global)

    Returns:
        List of memory dicts with uuid, content, name, trigger_task_types
    """
    repo = get_memory_repository()
    try:
        memories = await repo.get_triggered_references(task_type, group_id=group_id)
        return [MemoryRepository._to_dict(m) for m in memories]
    except Exception as e:
        logger.error("Failed to get triggered references for task_type=%s: %s", task_type, e)
        return []


async def get_phase_triggered_references(
    phase: str,
    group_id: str = "global",
) -> list[dict[str, Any]]:
    """
    Get reference memories that are triggered by a specific subtask phase.

    Returns reference-tier memories where the phase is in trigger_phases.
    Used for context-aware reference injection based on subtask phase.

    Args:
        phase: The phase to match against trigger_phases (e.g., backend, frontend, database)
        group_id: Group ID to filter memories (default: global)

    Returns:
        List of memory dicts with uuid, content, name, trigger_phases
    """
    repo = get_memory_repository()
    try:
        memories = await repo.get_phase_triggered_references(phase, group_id=group_id)
        return [MemoryRepository._to_dict(m) for m in memories]
    except Exception as e:
        logger.error("Failed to get phase triggered references for phase=%s: %s", phase, e)
        return []


async def get_episode_tags(
    episode_uuid: str,
) -> list[str]:
    """
    Get tags for a memory record.

    Args:
        episode_uuid: UUID of the memory to query

    Returns:
        List of tag strings (empty if memory not found or has no tags)
    """
    repo = get_memory_repository()
    try:
        data = await repo.get_as_dict(episode_uuid)
        if data is None:
            return []
        return data.get("tags") or []
    except Exception as e:
        logger.error("Failed to get tags for %s: %s", episode_uuid[:8], e)
        return []


async def get_all_distinct_tags(
    group_id: str = "global",
) -> list[str]:
    """
    Get all distinct tags across all memories in a group.

    Args:
        group_id: Group ID to filter memories

    Returns:
        Sorted list of distinct tag strings
    """
    repo = get_memory_repository()
    try:
        # Fetch all active memories in the group that have tags
        memories = await repo.list_by_scope_and_tier(
            group_id=group_id,
            status="active",
            limit=10000,
        )
        tag_set: set[str] = set()
        for mem in memories:
            if mem.tags:
                tag_set.update(mem.tags)
        return sorted(tag_set)
    except Exception as e:
        logger.error("Failed to get distinct tags: %s", e)
        return []


async def get_episodes_by_tags(
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    group_id: str = "global",
) -> list[dict[str, Any]]:
    """
    Get memories filtered by include/exclude tags.

    Args:
        include_tags: Memory must have at least one of these tags (empty/None = no filter)
        exclude_tags: Memory must NOT have any of these tags (empty/None = no filter)
        group_id: Group ID to filter memories

    Returns:
        List of memory dicts with uuid, content, name, tags
    """
    repo = get_memory_repository()
    try:
        memories = await repo.list_by_scope_and_tier(
            group_id=group_id,
            status="active",
            tags_include=include_tags,
            tags_exclude=exclude_tags,
            limit=10000,
            order_by="created_at",
        )
        return [MemoryRepository._to_dict(m) for m in memories]
    except Exception as e:
        logger.error("Failed to filter memories by tags: %s", e)
        return []
