"""Episode validation and access tracking operations."""

import logging

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


async def validate_episodes(
    driver: object = None,
    episode_uuids: list[str] | None = None,
) -> set[str]:
    """
    Validate which episode UUIDs actually exist in the database.

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
        episode_uuids: List of episode UUIDs to check

    Returns:
        Set of valid (existing) episode UUIDs
    """
    if not episode_uuids:
        return set()

    repo = get_memory_repository()
    return await repo.validate_ids(episode_uuids)


async def validate_episodes_with_content(
    driver: object = None,
    episode_uuids: list[str] | None = None,
) -> dict[str, str]:
    """
    Validate episode UUIDs and return their body content.

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
        episode_uuids: List of episode UUIDs to check

    Returns:
        Dict mapping valid episode UUID to its content (body text)
    """
    if not episode_uuids:
        return {}

    repo = get_memory_repository()
    batch = await repo.batch_get(episode_uuids)
    return {uid: data.get("content", "") for uid, data in batch.items()}


async def update_episode_access_time(
    driver: object = None,
    episode_uuids: list[str] | None = None,
) -> None:
    """
    Update loaded_count for accessed episodes (ACE-aligned tracking).

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
        episode_uuids: List of episode UUIDs that were accessed
    """
    if not episode_uuids:
        return

    repo = get_memory_repository()
    try:
        await repo.increment_loaded(episode_uuids)
        logger.debug("Updated access count for %d episodes", len(episode_uuids))
    except Exception as e:
        logger.warning("Failed to update episode access time: %s", e)


async def update_access_time(
    driver: object = None,
    uuids: list[str] | None = None,
) -> None:
    """
    Update last_accessed_at timestamp for accessed memory items.

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
        uuids: List of memory UUIDs that were accessed
    """
    if not uuids:
        return

    repo = get_memory_repository()
    try:
        await repo.increment_loaded(uuids)
        logger.debug("Updated access time for %d items", len(uuids))
    except Exception as e:
        logger.warning("Failed to update access time: %s", e)
