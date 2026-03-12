"""CRUD operations for memory episodes."""

import logging
from typing import Any

from .episode_operations_helpers import record_to_get_dict
from .repository import get_memory_repository

logger = logging.getLogger(__name__)


async def delete_episode(
    episode_uuid: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> bool:
    """
    Delete an episode from memory.

    Args:
        episode_uuid: UUID of the episode to delete

    Returns:
        True if deletion succeeded

    Raises:
        ValueError: If episode not found
    """
    repo = get_memory_repository()
    try:
        deleted = await repo.delete(
            episode_uuid,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        if not deleted:
            raise ValueError(f"Episode not found: {episode_uuid}")
        logger.info("Deleted episode: %s", episode_uuid)
        return True
    except ValueError:
        raise
    except Exception as e:
        logger.error("Failed to delete episode %s: %s", episode_uuid, e)
        raise


async def bulk_delete_episodes(
    episode_uuids: list[str],
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> dict[str, Any]:
    """
    Delete multiple episodes from memory.

    Args:
        episode_uuids: List of episode UUIDs to delete

    Returns:
        Dict with deleted count, failed count, and error details
    """
    repo = get_memory_repository()
    deleted = 0
    failed = 0
    errors: list[dict[str, str]] = []

    for uuid in episode_uuids:
        try:
            ok = await repo.delete(
                uuid,
                changed_by=changed_by,
                change_reason=change_reason,
            )
            if ok:
                deleted += 1
                logger.debug("Bulk deleted episode: %s", uuid)
            else:
                failed += 1
                errors.append({"id": uuid, "error": "Not found"})
        except Exception as e:
            failed += 1
            errors.append({"id": uuid, "error": str(e)})
            logger.warning("Bulk delete failed for %s: %s", uuid, e)

    logger.info("Bulk delete complete: %d deleted, %d failed", deleted, failed)
    return {"deleted": deleted, "failed": failed, "errors": errors}


async def get_episode_details(episode_uuid: str) -> dict[str, Any] | None:
    """
    Get detailed information about a single episode including usage stats.

    Args:
        episode_uuid: UUID of the episode to retrieve

    Returns:
        Dict with episode details and usage stats, or None if not found
    """
    repo = get_memory_repository()
    result = await repo.get_as_dict(episode_uuid)
    if result is None:
        return None
    return record_to_get_dict(result)


async def batch_get_episode_details(
    episode_uuids: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Get multiple episodes in a single query for efficient batch retrieval.

    Args:
        episode_uuids: List of episode UUIDs to retrieve

    Returns:
        Dict mapping UUID to episode details (missing UUIDs not included)
    """
    repo = get_memory_repository()
    batch = await repo.batch_get(episode_uuids)
    return {uuid: record_to_get_dict(data) for uuid, data in batch.items()}
