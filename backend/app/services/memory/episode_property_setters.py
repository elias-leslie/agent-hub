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

from app.services.memory.memory_utils import resolve_uuid_prefix
from app.services.memory.repository import get_memory_repository

from .applicability import (
    normalize_applicability,
    normalize_context_kind,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)

logger = logging.getLogger(__name__)


async def _set_episode_property(
    episode_uuid: str,
    field_name: str,
    value: Any,
    description: str = "",
    *,
    change_reason: str | None = None,
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
        episode_uuid = await resolve_uuid_prefix(episode_uuid)
        result = await repo.update(
            episode_uuid,
            changed_by="api",
            change_reason=change_reason,
            **{field_name: value},
        )
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
    *,
    change_reason: str | None = None,
) -> bool:
    """Set injection_tier on a memory record.

    Valid tiers: mandate, guardrail, reference, pending_review
    """
    return await _set_episode_property(
        episode_uuid, "injection_tier", injection_tier,
        f"set injection_tier={injection_tier}",
        change_reason=change_reason,
    )


async def set_episode_pinned(
    episode_uuid: str,
    pinned: bool,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set pinned on a memory record. Pinned memories are never auto-demoted."""
    return await _set_episode_property(
        episode_uuid, "pinned", pinned,
        f"set pinned={pinned}",
        change_reason=change_reason,
    )


async def set_episode_auto_inject(
    episode_uuid: str,
    auto_inject: bool,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set auto_inject on a memory record. Auto-injected references behave like mandates."""
    return await _set_episode_property(
        episode_uuid, "auto_inject", auto_inject,
        f"set auto_inject={auto_inject}",
        change_reason=change_reason,
    )


async def set_episode_display_order(
    episode_uuid: str,
    display_order: int,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set display_order on a memory record. Lower values = earlier injection."""
    return await _set_episode_property(
        episode_uuid, "display_order", display_order,
        f"set display_order={display_order}",
        change_reason=change_reason,
    )


async def set_episode_render_mode(
    episode_uuid: str,
    render_mode: str | None,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set render_mode on a memory record.

    Valid values: 'full', 'compact', 'summary', or None (auto/profile-driven).
    """
    if render_mode is not None and render_mode not in ("full", "compact", "summary"):
        raise ValueError(
            f"Invalid render_mode {render_mode!r}; must be 'full', 'compact', 'summary', or None"
        )
    return await _set_episode_property(
        episode_uuid, "render_mode", render_mode,
        f"set render_mode={render_mode}",
        change_reason=change_reason,
    )


async def set_episode_trigger_task_types(
    episode_uuid: str,
    trigger_task_types: list[str],
    *,
    change_reason: str | None = None,
) -> bool:
    """Set trigger_task_types on a memory record."""
    normalized = normalize_trigger_task_types(trigger_task_types)
    return await _set_episode_property(
        episode_uuid, "trigger_task_types", normalized,
        f"set trigger_task_types={normalized}",
        change_reason=change_reason,
    )


async def set_episode_trigger_phases(
    episode_uuid: str,
    trigger_phases: list[str],
    *,
    change_reason: str | None = None,
) -> bool:
    """Set trigger_phases on a memory record."""
    normalized = normalize_trigger_phases(trigger_phases)
    return await _set_episode_property(
        episode_uuid, "trigger_phases", normalized,
        f"set trigger_phases={normalized}",
        change_reason=change_reason,
    )


async def set_episode_tags(
    episode_uuid: str,
    tags: list[str],
    *,
    change_reason: str | None = None,
) -> bool:
    """Set tags on a memory record. Used for per-agent memory filtering."""
    return await _set_episode_property(
        episode_uuid, "tags", tags,
        f"set tags={tags}",
        change_reason=change_reason,
    )


async def set_episode_context_kind(
    episode_uuid: str,
    context_kind: str,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set context_kind on a memory record."""
    normalized = normalize_context_kind(context_kind).value
    return await _set_episode_property(
        episode_uuid,
        "context_kind",
        normalized,
        f"set context_kind={normalized}",
        change_reason=change_reason,
    )


async def set_episode_applicability(
    episode_uuid: str,
    applicability: dict[str, Any],
    *,
    change_reason: str | None = None,
) -> bool:
    """Set applicability on a memory record."""
    normalized = normalize_applicability(applicability).model_dump()
    return await _set_episode_property(
        episode_uuid,
        "applicability",
        normalized,
        "set applicability",
        change_reason=change_reason,
    )


async def set_episode_summary(
    episode_uuid: str,
    summary: str,
    *,
    change_reason: str | None = None,
) -> bool:
    """Set summary on a memory record. ~20 char action phrase for TOON index."""
    return await _set_episode_property(
        episode_uuid, "summary", summary,
        f"set summary={summary[:20]}",
        change_reason=change_reason,
    )
