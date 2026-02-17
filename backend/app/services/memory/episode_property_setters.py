"""
Individual property setters for Episodic nodes.

Provides single-episode update functions for:
- injection_tier: mandate/guardrail/reference/pending_review
- pinned: Never auto-demote
- auto_inject: Always inject (for reference tier)
- display_order: Injection ordering within tier
- trigger_task_types: Auto-inject when task_type matches
- trigger_phases: Auto-inject when subtask phase matches
- summary: Short action phrase for TOON index
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver

from app.services.memory.neo4j_queries import execute_episode_update


async def _set_episode_property(
    episode_uuid: str,
    field_name: str,
    value: Any,
    driver: AsyncDriver | None = None,
    description: str = "",
) -> bool:
    """Set a single property on an Episodic node.

    Args:
        episode_uuid: UUID of the episode to update
        field_name: Cypher property name to set
        value: New value for the property
        driver: Neo4j driver (uses Graphiti's driver if not provided)
        description: Human-readable description for logging

    Returns:
        True if updated, False if episode not found
    """
    query = f"""
    MATCH (e:Episodic {{uuid: $uuid}})
    SET e.{field_name} = $value
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "value": value},
        episode_uuid,
        driver,
        description,
    )


async def set_episode_injection_tier(
    episode_uuid: str,
    injection_tier: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """Set injection_tier on an Episodic node.

    Valid tiers: mandate, guardrail, reference, pending_review
    """
    return await _set_episode_property(
        episode_uuid, "injection_tier", injection_tier, driver,
        f"set injection_tier={injection_tier}",
    )


async def set_episode_pinned(
    episode_uuid: str,
    pinned: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """Set pinned on an Episodic node. Pinned episodes are never auto-demoted."""
    return await _set_episode_property(
        episode_uuid, "pinned", pinned, driver,
        f"set pinned={pinned}",
    )


async def set_episode_auto_inject(
    episode_uuid: str,
    auto_inject: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """Set auto_inject on an Episodic node. Auto-injected references behave like mandates."""
    return await _set_episode_property(
        episode_uuid, "auto_inject", auto_inject, driver,
        f"set auto_inject={auto_inject}",
    )


async def set_episode_display_order(
    episode_uuid: str,
    display_order: int,
    driver: AsyncDriver | None = None,
) -> bool:
    """Set display_order on an Episodic node. Lower values = earlier injection."""
    return await _set_episode_property(
        episode_uuid, "display_order", display_order, driver,
        f"set display_order={display_order}",
    )


async def set_episode_trigger_task_types(
    episode_uuid: str,
    trigger_task_types: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """Set trigger_task_types on an Episodic node."""
    return await _set_episode_property(
        episode_uuid, "trigger_task_types", trigger_task_types, driver,
        f"set trigger_task_types={trigger_task_types}",
    )


async def set_episode_trigger_phases(
    episode_uuid: str,
    trigger_phases: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """Set trigger_phases on an Episodic node."""
    return await _set_episode_property(
        episode_uuid, "trigger_phases", trigger_phases, driver,
        f"set trigger_phases={trigger_phases}",
    )


async def set_episode_tags(
    episode_uuid: str,
    tags: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """Set tags on an Episodic node. Used for per-agent memory filtering."""
    return await _set_episode_property(
        episode_uuid, "tags", tags, driver,
        f"set tags={tags}",
    )


async def set_episode_summary(
    episode_uuid: str,
    summary: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """Set summary on an Episodic node. ~20 char action phrase for TOON index."""
    return await _set_episode_property(
        episode_uuid, "summary", summary, driver,
        f"set summary={summary[:20]}",
    )
