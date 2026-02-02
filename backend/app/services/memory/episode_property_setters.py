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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver

from app.services.memory.neo4j_queries import execute_episode_update


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
        query,
        {"uuid": episode_uuid, "pinned": pinned},
        episode_uuid,
        driver,
        f"set pinned={pinned}",
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


async def set_episode_trigger_phases(
    episode_uuid: str,
    trigger_phases: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set trigger_phases property on an Episodic node.

    Specifies which subtask phases should automatically inject this reference episode.
    Common phases: backend, frontend, database, verification, research, testing.

    Args:
        episode_uuid: UUID of the episode to update
        trigger_phases: List of phase strings that trigger this episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.trigger_phases = $trigger_phases
    RETURN e.uuid AS uuid
    """
    return await execute_episode_update(
        query,
        {"uuid": episode_uuid, "trigger_phases": trigger_phases},
        episode_uuid,
        driver,
        f"set trigger_phases={trigger_phases}",
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
        query,
        {"uuid": episode_uuid, "summary": summary},
        episode_uuid,
        driver,
        f"set summary={summary[:20]}",
    )
