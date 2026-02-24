"""
Individual property setters for memory records.

Provides single-memory update functions for:
- injection_tier: mandate/guardrail/reference/pending_review
- pinned: Never auto-demote
- auto_inject: Always inject (for reference tier)
- display_order: Injection ordering within tier
- trigger_task_types: Auto-inject when task_type matches
- trigger_phases: Auto-inject when subtask phase matches
- summary: Short action phrase for TOON index
- tags: Per-agent memory filtering

All functions delegate to MemoryRepository.update().
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.memory.repository import get_memory_repository

logger = logging.getLogger(__name__)


async def _set_episode_property(
    episode_uuid: str,
    field_name: str,
    value: Any,
    description: str = "",
) -> bool:
    """Set a single property on a memory record.

    Args:
        episode_uuid: UUID of the memory to update
        field_name: Column name to set
        value: New value for the property
        description: Human-readable description for logging

    Returns:
        True if updated, False if memory not found
    """
    repo = get_memory_repository()
    try:
        result = await repo.update(episode_uuid, **{field_name: value})
        if result:
            logger.debug("%s succeeded for memory %s", description, episode_uuid[:8])
        else:
            logger.warning("Memory %s not found for %s", episode_uuid[:8], description)
        return result
    except Exception as e:
        logger.error("Failed %s for %s: %s", description, episode_uuid[:8], e)
        return False


async def set_episode_injection_tier(
    episode_uuid: str,
    injection_tier: str,
) -> bool:
    """Set injection_tier on a memory record.

    Valid tiers: mandate, guardrail, reference, pending_review
    """
    return await _set_episode_property(
        episode_uuid, "injection_tier", injection_tier,
        f"set injection_tier={injection_tier}",
    )


async def set_episode_pinned(
    episode_uuid: str,
    pinned: bool,
) -> bool:
    """Set pinned on a memory record. Pinned memories are never auto-demoted."""
    return await _set_episode_property(
        episode_uuid, "pinned", pinned,
        f"set pinned={pinned}",
    )


async def set_episode_auto_inject(
    episode_uuid: str,
    auto_inject: bool,
) -> bool:
    """Set auto_inject on a memory record. Auto-injected references behave like mandates."""
    return await _set_episode_property(
        episode_uuid, "auto_inject", auto_inject,
        f"set auto_inject={auto_inject}",
    )


async def set_episode_display_order(
    episode_uuid: str,
    display_order: int,
) -> bool:
    """Set display_order on a memory record. Lower values = earlier injection."""
    return await _set_episode_property(
        episode_uuid, "display_order", display_order,
        f"set display_order={display_order}",
    )


async def set_episode_trigger_task_types(
    episode_uuid: str,
    trigger_task_types: list[str],
) -> bool:
    """Set trigger_task_types on a memory record."""
    return await _set_episode_property(
        episode_uuid, "trigger_task_types", trigger_task_types,
        f"set trigger_task_types={trigger_task_types}",
    )


async def set_episode_trigger_phases(
    episode_uuid: str,
    trigger_phases: list[str],
) -> bool:
    """Set trigger_phases on a memory record."""
    return await _set_episode_property(
        episode_uuid, "trigger_phases", trigger_phases,
        f"set trigger_phases={trigger_phases}",
    )


async def set_episode_tags(
    episode_uuid: str,
    tags: list[str],
) -> bool:
    """Set tags on a memory record. Used for per-agent memory filtering."""
    return await _set_episode_property(
        episode_uuid, "tags", tags,
        f"set tags={tags}",
    )


async def set_episode_summary(
    episode_uuid: str,
    summary: str,
) -> bool:
    """Set summary on a memory record. ~20 char action phrase for TOON index."""
    return await _set_episode_property(
        episode_uuid, "summary", summary,
        f"set summary={summary[:20]}",
    )
