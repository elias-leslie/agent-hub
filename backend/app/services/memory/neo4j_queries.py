"""
Neo4j query execution helpers for Graphiti episode management.

Provides utilities for executing Neo4j queries with proper driver handling
and error logging.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


async def execute_episode_query(
    query: str,
    params: dict[str, Any],
    driver: AsyncDriver | None = None,
    operation: str = "query",
) -> list[dict[str, Any]]:
    """
    Execute a Neo4j query and return results as list of dicts.

    Args:
        query: Cypher query to execute
        params: Query parameters
        driver: Neo4j driver (uses Graphiti's driver if not provided)
        operation: Operation description for logging

    Returns:
        List of result records as dicts
    """
    if driver is None:
        from app.services.memory.graphiti_client import get_graphiti

        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    try:
        records, _, _ = await driver.execute_query(query, **params)
        return [dict(r) for r in records]
    except Exception as e:
        logger.error("Failed to execute %s: %s", operation, e)
        raise


async def execute_episode_update(
    query: str,
    params: dict[str, Any],
    episode_uuid: str,
    driver: AsyncDriver | None = None,
    operation: str = "update",
) -> bool:
    """
    Execute a Neo4j update query on a single episode.

    Args:
        query: Cypher query to execute
        params: Query parameters (must include 'uuid')
        episode_uuid: UUID of the episode being updated (for logging)
        driver: Neo4j driver (uses Graphiti's driver if not provided)
        operation: Operation description for logging

    Returns:
        True if updated, False if episode not found
    """
    try:
        records = await execute_episode_query(query, params, driver, operation)
        if records:
            logger.debug("%s succeeded for episode %s", operation, episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for %s", episode_uuid[:8], operation)
        return False
    except Exception as e:
        logger.error("Failed %s for %s: %s", operation, episode_uuid[:8], e)
        return False


async def execute_batch_update(
    query: str,
    updates: list[dict[str, Any]],
    driver: AsyncDriver | None = None,
    operation: str = "batch update",
) -> dict[str, bool]:
    """
    Execute a batch update query on multiple episodes.

    Args:
        query: Cypher query with UNWIND $updates pattern
        updates: List of update parameter dicts (each must have 'uuid')
        driver: Neo4j driver (uses Graphiti's driver if not provided)
        operation: Operation description for logging

    Returns:
        Dict mapping episode_uuid to success status (True if updated)
    """
    if not updates:
        return {}

    try:
        records = await execute_episode_query(query, {"updates": updates}, driver, operation)
        updated_uuids = {record["uuid"] for record in records}

        results = {}
        for update in updates:
            uuid = update.get("uuid", "")
            results[uuid] = uuid in updated_uuids

        updated_count = sum(1 for success in results.values() if success)
        logger.info("%s: %d/%d episodes updated", operation, updated_count, len(updates))
        return results
    except Exception:
        return {update.get("uuid", ""): False for update in updates}
