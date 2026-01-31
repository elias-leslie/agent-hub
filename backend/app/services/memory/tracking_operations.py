"""
Episode validation and access tracking operations.

Handles validation of episode UUIDs and updating access timestamps.
"""

import logging
from typing import Any

from graphiti_core.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


async def validate_episodes(
    driver: Any,
    episode_uuids: list[str],
) -> set[str]:
    """
    Validate which episode UUIDs actually exist in the database.

    Args:
        driver: Neo4j driver instance
        episode_uuids: List of episode UUIDs to check

    Returns:
        Set of valid (existing) episode UUIDs
    """
    if not episode_uuids:
        return set()

    unique_uuids = list(set(episode_uuids))
    query = """
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {uuid: uuid})
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(query, uuids=unique_uuids)
        return {str(r["uuid"]) for r in records}
    except Exception as e:
        logger.warning("Failed to validate episodes: %s", e)
        return set()


async def update_episode_access_time(
    driver: Any,
    episode_uuids: list[str],
) -> None:
    """
    Update loaded_count for accessed episodes (ACE-aligned tracking).

    Args:
        driver: Neo4j driver instance
        episode_uuids: List of episode UUIDs that were accessed
    """
    if not episode_uuids:
        return

    query = """
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {uuid: uuid})
    SET e.loaded_count = coalesce(e.loaded_count, 0) + 1
    """

    try:
        await driver.execute_query(query, uuids=episode_uuids)
        logger.debug("Updated access count for %d episodes", len(episode_uuids))
    except Exception as e:
        logger.warning("Failed to update episode access time: %s", e)


async def update_access_time(
    driver: Any,
    uuids: list[str],
) -> None:
    """
    Update last_accessed_at timestamp for accessed memory items.

    Args:
        driver: Neo4j driver instance
        uuids: List of edge/episode UUIDs that were accessed
    """
    if not uuids:
        return

    now = utc_now().isoformat()
    query = """
    UNWIND $uuids AS uuid
    MATCH (e:EntityEdge {uuid: uuid})
    SET e.last_accessed_at = datetime($now)
    """

    try:
        await driver.execute_query(query, uuids=uuids, now=now)
        logger.debug("Updated access time for %d items", len(uuids))
    except Exception as e:
        logger.warning("Failed to update access time: %s", e)
