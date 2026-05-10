"""
Episode property management for memory records.

Extends memory records with custom properties for the memory system:
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
from typing import Any

# Re-export all query functions
from app.services.memory.episode_property_queries import (
    get_all_distinct_tags,
    get_episode_properties,
    get_episode_tags,
    get_episodes_by_tags,
    get_phase_triggered_references,
    get_triggered_references,
)

# Re-export all individual setters
from app.services.memory.episode_property_setters import (
    set_episode_applicability,
    set_episode_auto_inject,
    set_episode_context_kind,
    set_episode_display_order,
    set_episode_injection_tier,
    set_episode_pinned,
    set_episode_summary,
    set_episode_tags,
    set_episode_trigger_phases,
    set_episode_trigger_task_types,
)
from app.services.memory.repository import get_memory_repository

logger = logging.getLogger(__name__)

# Make re-exported functions available for star imports
__all__ = [
    "batch_set_episode_injection_tier",
    "batch_update_episode_properties",
    "copy_episode_stats",
    "get_all_distinct_tags",
    "get_episode_properties",
    "get_episode_tags",
    "get_episodes_by_tags",
    "get_phase_triggered_references",
    "get_triggered_references",
    "init_episode_usage_properties",
    "set_episode_applicability",
    "set_episode_auto_inject",
    "set_episode_context_kind",
    "set_episode_display_order",
    "set_episode_injection_tier",
    "set_episode_pinned",
    "set_episode_summary",
    "set_episode_tags",
    "set_episode_trigger_phases",
    "set_episode_trigger_task_types",
]


async def batch_set_episode_injection_tier(
    updates: list[tuple[str, str]],
) -> dict[str, bool]:
    """
    Batch update injection_tier for multiple memories.

    Args:
        updates: List of (memory_uuid, injection_tier) tuples

    Returns:
        Dict mapping memory_uuid to success status (True if updated)
    """
    repo = get_memory_repository()
    update_dicts = [{"uuid": uuid, "injection_tier": tier} for uuid, tier in updates]
    return await repo.batch_update_properties(update_dicts)


async def batch_update_episode_properties(
    updates: list[dict[str, Any]],
) -> dict[str, bool]:
    """
    Batch update properties for multiple memories.

    Supports updating: injection_tier, summary, trigger_task_types, trigger_phases,
    pinned, auto_inject, display_order, tags.
    Only provided fields are updated (partial update).

    Args:
        updates: List of dicts with 'uuid' and optional property fields

    Returns:
        Dict mapping memory_uuid to success status (True if updated)
    """
    repo = get_memory_repository()
    return await repo.batch_update_properties(updates)


async def init_episode_usage_properties(
    episode_uuid: str,
) -> bool:
    """
    Initialize usage tracking properties on a memory record.

    No-op for PostgreSQL — defaults handle initialization via server_default="0".

    Args:
        episode_uuid: UUID of the memory to initialize

    Returns:
        True (always succeeds — defaults are set at creation time)
    """
    return True


async def copy_episode_stats(
    source_uuid: str,
    target_uuid: str,
) -> bool:
    """
    Copy usage stats from one memory to another.

    Copies loaded_count, referenced_count, helpful_count, harmful_count,
    pinned, auto_inject, display_order, summary, trigger_task_types,
    trigger_phases, tags, and created_at. Used when editing memories
    (delete + recreate) to preserve feedback data AND list position — the
    memory list sorts on (display_order, created_at desc), so without
    copying created_at the edited memory would jump within its bucket.

    Args:
        source_uuid: UUID of the memory to copy stats from
        target_uuid: UUID of the memory to copy stats to

    Returns:
        True if copied, False if source or target not found
    """
    repo = get_memory_repository()
    try:
        source = await repo.get_as_dict(source_uuid)
        if not source:
            logger.warning(
                "Failed to copy stats: source %s not found",
                source_uuid[:8],
            )
            return False

        update_kwargs: dict[str, object] = {
            "loaded_count": source.get("loaded_count", 0),
            "referenced_count": source.get("referenced_count", 0),
            "helpful_count": source.get("helpful_count", 0),
            "harmful_count": source.get("harmful_count", 0),
            "pinned": source.get("pinned", False),
            "auto_inject": source.get("auto_inject", False),
            "display_order": source.get("display_order", 50),
            "summary": source.get("summary"),
            "trigger_task_types": source.get("trigger_task_types"),
            "trigger_phases": source.get("trigger_phases"),
            "tags": source.get("tags"),
            "context_kind": source.get("context_kind", "reference"),
            "applicability": source.get("applicability") or {},
        }
        source_created_at = source.get("created_at")
        if source_created_at is not None:
            update_kwargs["created_at"] = source_created_at
        ok = await repo.update(target_uuid, **update_kwargs)

        if ok:
            logger.debug("Copied stats from %s to %s", source_uuid[:8], target_uuid[:8])
        else:
            logger.warning(
                "Failed to copy stats: target %s not found",
                target_uuid[:8],
            )
        return ok
    except Exception as e:
        logger.error("Failed to copy stats from %s to %s: %s", source_uuid[:8], target_uuid[:8], e)
        return False
