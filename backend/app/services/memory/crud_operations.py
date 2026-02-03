"""CRUD operations for memory episodes."""

import logging
from typing import Any

from graphiti_core import Graphiti

from .memory_queries import batch_get_episodes, get_episode

logger = logging.getLogger(__name__)


async def delete_episode(graphiti: Graphiti, episode_uuid: str) -> bool:
    """
    Delete an episode from memory.

    Args:
        graphiti: Graphiti client instance
        episode_uuid: UUID of the episode to delete

    Returns:
        True if deletion succeeded

    Raises:
        ValueError: If episode not found
    """
    try:
        await graphiti.remove_episode(episode_uuid)
        logger.info("Deleted episode: %s", episode_uuid)
        return True
    except Exception as e:
        logger.error("Failed to delete episode %s: %s", episode_uuid, e)
        raise


async def bulk_delete_episodes(graphiti: Graphiti, episode_uuids: list[str]) -> dict[str, Any]:
    """
    Delete multiple episodes from memory.

    Args:
        graphiti: Graphiti client instance
        episode_uuids: List of episode UUIDs to delete

    Returns:
        Dict with deleted count, failed count, and error details
    """
    deleted = 0
    failed = 0
    errors: list[dict[str, str]] = []

    for uuid in episode_uuids:
        try:
            await graphiti.remove_episode(uuid)
            deleted += 1
            logger.debug("Bulk deleted episode: %s", uuid)
        except Exception as e:
            failed += 1
            errors.append({"id": uuid, "error": str(e)})
            logger.warning("Bulk delete failed for %s: %s", uuid, e)

    logger.info("Bulk delete complete: %d deleted, %d failed", deleted, failed)
    return {"deleted": deleted, "failed": failed, "errors": errors}


async def get_episode_details(driver: Any, episode_uuid: str) -> dict[str, Any] | None:
    """
    Get detailed information about a single episode including usage stats.

    Args:
        driver: Neo4j driver
        episode_uuid: UUID of the episode to retrieve

    Returns:
        Dict with episode details and usage stats, or None if not found
    """
    return await get_episode(driver, episode_uuid)


async def batch_get_episode_details(
    driver: Any, episode_uuids: list[str]
) -> dict[str, dict[str, Any]]:
    """
    Get multiple episodes in a single query for efficient batch retrieval.

    Args:
        driver: Neo4j driver
        episode_uuids: List of episode UUIDs to retrieve

    Returns:
        Dict mapping UUID to episode details (missing UUIDs not included)
    """
    return await batch_get_episodes(driver, episode_uuids)
