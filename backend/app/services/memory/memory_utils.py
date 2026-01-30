"""
Utility functions for memory service.

Contains helper functions for group ID building, UUID resolution, and type mapping.
"""

import logging
from typing import Any

from graphiti_core.nodes import EpisodeType

from .memory_models import MemoryScope, MemorySource

logger = logging.getLogger(__name__)


def build_group_id(scope: MemoryScope, scope_id: str | None = None) -> str:
    """
    Build Graphiti group_id from scope and scope_id.

    This is the canonical implementation - use this instead of duplicating logic.
    Graphiti only allows alphanumeric, dashes, and underscores in group_id.

    Args:
        scope: Memory scope (GLOBAL, PROJECT)
        scope_id: Identifier for the scope (project_id)

    Returns:
        Sanitized group_id string for Graphiti
    """
    if scope == MemoryScope.GLOBAL:
        return "global"

    # Sanitize scope_id: replace invalid characters with dashes
    safe_id = (scope_id or "default").replace(":", "-").replace("/", "-")

    if scope == MemoryScope.PROJECT:
        return f"project-{safe_id}"

    # Should not reach here with current enum values
    raise ValueError(f"Unknown scope: {scope}")


async def resolve_uuid_prefix_with_driver(
    driver: Any,
    uuid_or_prefix: str,
    group_id: str = "global",
) -> str:
    """
    Resolve a UUID prefix (8-char) or full UUID to a full UUID.

    If the input is already a full UUID format (contains hyphens), returns it as-is.
    Otherwise, queries Neo4j to find the matching episode UUID.

    Args:
        driver: Neo4j driver instance
        uuid_or_prefix: Either a full UUID or an 8-char prefix
        group_id: Graphiti group ID for scoping

    Returns:
        Full UUID string

    Raises:
        ValueError: If prefix is ambiguous (multiple matches) or not found
    """
    # If already a full UUID (contains hyphens), return as-is
    if "-" in uuid_or_prefix:
        return uuid_or_prefix

    # Query Neo4j for matching episodes
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.uuid STARTS WITH $prefix
    RETURN e.uuid AS full_uuid
    LIMIT 2
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            prefix=uuid_or_prefix,
            group_id=group_id,
        )

        if not records:
            raise ValueError(f"Episode not found with UUID prefix: {uuid_or_prefix}")

        if len(records) > 1:
            # Ambiguous prefix - multiple matches
            uuids = [str(r["full_uuid"]) for r in records]
            raise ValueError(
                f"Ambiguous UUID prefix '{uuid_or_prefix}' matches multiple episodes: "
                f"{', '.join(u[:8] for u in uuids)}. Please provide more characters."
            )

        return str(records[0]["full_uuid"])

    except Exception as e:
        if isinstance(e, ValueError):
            raise
        logger.error("Failed to resolve UUID prefix %s: %s", uuid_or_prefix, e)
        raise ValueError(f"Failed to resolve UUID prefix: {uuid_or_prefix}") from e


async def resolve_uuid_prefix(
    uuid_or_prefix: str,
    group_id: str = "global",
) -> str:
    """
    Resolve a UUID prefix (8-char) or full UUID to a full UUID.

    Uses the global Graphiti instance.

    Args:
        uuid_or_prefix: Either a full UUID or an 8-char prefix
        group_id: Graphiti group ID for scoping

    Returns:
        Full UUID string

    Raises:
        ValueError: If prefix is ambiguous (multiple matches) or not found
    """
    from .graphiti_client import get_graphiti

    graphiti = get_graphiti()
    return await resolve_uuid_prefix_with_driver(graphiti.driver, uuid_or_prefix, group_id)


def map_episode_type(ep_type: EpisodeType) -> MemorySource:
    """
    Map Graphiti EpisodeType to our MemorySource.

    Args:
        ep_type: Graphiti episode type

    Returns:
        Corresponding MemorySource enum value
    """
    # EpisodeType is message, json, text
    # Default to CHAT for message type
    if ep_type == EpisodeType.message:
        return MemorySource.CHAT
    else:
        return MemorySource.SYSTEM
