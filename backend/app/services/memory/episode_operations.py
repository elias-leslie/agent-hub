"""
Episode CRUD and search operations.

Handles fetching, batch operations, and text search for memories.
All operations delegate to MemoryRepository.
"""

import logging
from datetime import datetime
from typing import Any

from .episode_operations_helpers import record_to_episode, record_to_get_dict
from .memory_models import MemoryCategory
from .repository import MemoryRepository, get_memory_repository

logger = logging.getLogger(__name__)

# Private alias preserved for any internal callers.
_record_to_episode = record_to_episode


async def get_episode(driver: Any, episode_uuid: str) -> dict[str, Any] | None:
    """Get detailed information about a single memory including usage stats.

    Args:
        driver: Ignored (kept for backward compat)
        episode_uuid: UUID of the memory to fetch

    Returns:
        Dict with memory details, or None if not found
    """
    del driver
    repo = get_memory_repository()
    try:
        data = await repo.get_as_dict(episode_uuid)
        if data is None:
            return None
        return record_to_get_dict(data)
    except Exception as e:
        logger.error("Failed to get episode %s: %s", episode_uuid, e)
        return None


async def batch_get_episodes(
    driver: Any, episode_uuids: list[str]
) -> dict[str, dict[str, Any]]:
    """Get multiple memories in a single query for efficient batch retrieval.

    Args:
        driver: Ignored (kept for backward compat)
        episode_uuids: List of memory UUIDs to fetch

    Returns:
        Dict mapping UUID to memory detail dict
    """
    del driver
    if not episode_uuids:
        return {}
    repo = get_memory_repository()
    try:
        batch = await repo.batch_get(episode_uuids)
        results = {uuid: record_to_get_dict(data) for uuid, data in batch.items()}
        logger.debug("Batch get: %d/%d episodes found", len(results), len(episode_uuids))
        return results
    except Exception as e:
        logger.error("Failed to batch get episodes: %s", e)
        return {}


async def fetch_episodes_filtered(
    driver: Any,
    group_id: str | None,
    limit: int,
    reference_time: datetime,
    category: MemoryCategory | None = None,
) -> tuple[list[Any], bool]:
    """Fetch memories with optional category filtering at database level.

    Args:
        driver: Ignored (kept for backward compat)
        group_id: Group ID to filter memories
        limit: Max number of results
        reference_time: Only include memories created at or before this time
        category: Optional tier category filter

    Returns:
        Tuple of (list of episode-like objects, has_more flag)
    """
    del driver
    repo = get_memory_repository()

    # Map category to tier for filtering
    tier: int | str | None = None
    if category:
        tier = category.value  # e.g., "mandate", "guardrail", "reference"

    memories = await repo.list_by_scope_and_tier(
        group_id=group_id,
        tier=tier,
        status="active",
        limit=limit + 1,
        order_by="created_at",
    )

    # Filter by reference_time (valid_at <= reference_time)
    filtered = [m for m in memories if m.valid_at is None or m.valid_at <= reference_time]

    has_more = len(filtered) > limit
    result_memories = filtered[:limit]

    # Convert to episode-like dicts then to SimpleNamespace objects
    return [record_to_episode(MemoryRepository._to_dict(m)) for m in result_memories], has_more


async def text_search_episodes(
    driver: Any,
    group_id: str | None,
    query: str,
    limit: int = 50,
    category: MemoryCategory | None = None,
) -> list[Any]:
    """Text-based search on memory content, name, summary, and tier.

    Args:
        driver: Ignored (kept for backward compat)
        group_id: Group ID to filter memories
        query: Search text
        limit: Max number of results
        category: Optional tier category filter

    Returns:
        List of episode-like objects matching the search
    """
    del driver
    repo = get_memory_repository()

    # Map category to tier name for filtering
    category_str: str | None = category.value if category else None

    try:
        memories = await repo.text_search(
            query,
            group_id=group_id,
            category=category_str,
            limit=limit,
        )
        return [record_to_episode(MemoryRepository._to_dict(m)) for m in memories]
    except Exception as e:
        logger.error("Text search failed: %s", e)
        return []
