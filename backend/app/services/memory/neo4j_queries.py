"""
Backward-compatibility shim for Neo4j query execution helpers.

These functions previously executed Cypher queries against Neo4j.
They now delegate to MemoryRepository (PostgreSQL) for all operations.

Callers should migrate to using MemoryRepository directly.
"""

from __future__ import annotations

import logging
from typing import Any

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


async def execute_episode_query(
    query: str = "",
    params: dict[str, Any] | None = None,
    driver: Any = None,
    operation: str = "query",
) -> list[dict[str, Any]]:
    """
    Backward-compat shim. Previously executed a Neo4j Cypher query.

    Now delegates to MemoryRepository. Since callers pass Cypher queries
    which can't be translated generically, this returns an empty list.
    Callers should migrate to MemoryRepository methods directly.

    Args:
        query: Unused (was Cypher query)
        params: Query parameters — may contain 'uuid' or 'uuids'
        driver: Unused (was Neo4j driver)
        operation: Operation description for logging

    Returns:
        List of result records as dicts
    """
    params = params or {}
    repo = get_memory_repository()

    # Try to handle common patterns
    uuid_val = params.get("uuid")
    if uuid_val:
        result = await repo.get_as_dict(uuid_val)
        return [result] if result else []

    uuids_val = params.get("uuids")
    if uuids_val:
        batch = await repo.batch_get(uuids_val)
        return list(batch.values())

    logger.warning(
        "execute_episode_query called with unrecognized params for '%s'. "
        "Migrate to MemoryRepository methods.",
        operation,
    )
    return []


async def execute_episode_update(
    query: str = "",
    params: dict[str, Any] | None = None,
    episode_uuid: str = "",
    driver: Any = None,
    operation: str = "update",
) -> bool:
    """
    Backward-compat shim. Previously executed a Neo4j update query.

    Now delegates to MemoryRepository.update().

    Args:
        query: Unused (was Cypher query)
        params: Query parameters — should contain fields to update
        episode_uuid: UUID of the episode being updated
        driver: Unused (was Neo4j driver)
        operation: Operation description for logging

    Returns:
        True if updated, False if episode not found
    """
    params = params or {}
    repo = get_memory_repository()

    # Remove 'uuid' from params since it's the identifier, not a field to set
    update_fields = {k: v for k, v in params.items() if k != "uuid"}

    try:
        ok = await repo.update(episode_uuid, **update_fields)
        if ok:
            logger.debug("%s succeeded for episode %s", operation, episode_uuid[:8])
        else:
            logger.warning("Episode %s not found for %s", episode_uuid[:8], operation)
        return ok
    except Exception as e:
        logger.error("Failed %s for %s: %s", operation, episode_uuid[:8], e)
        return False


async def execute_batch_update(
    query: str = "",
    updates: list[dict[str, Any]] | None = None,
    driver: Any = None,
    operation: str = "batch update",
) -> dict[str, bool]:
    """
    Backward-compat shim. Previously executed a batch Neo4j update.

    Now delegates to MemoryRepository.batch_update_properties().

    Args:
        query: Unused (was Cypher query)
        updates: List of update parameter dicts (each must have 'uuid')
        driver: Unused (was Neo4j driver)
        operation: Operation description for logging

    Returns:
        Dict mapping episode_uuid to success status (True if updated)
    """
    if not updates:
        return {}

    repo = get_memory_repository()
    return await repo.batch_update_properties(updates)
