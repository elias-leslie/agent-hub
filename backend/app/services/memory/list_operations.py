"""List and pagination operations for memory episodes."""

from datetime import datetime, timedelta
from typing import Any

from graphiti_core.utils.datetime_utils import utc_now

from .episode_converters import convert_raw_episodes
from .memory_models import MemoryCategory, MemoryListResult, MemoryScope
from .memory_queries import fetch_episodes_filtered


async def list_episodes_paginated(
    driver: Any,
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    limit: int = 50,
    cursor: str | None = None,
    category: MemoryCategory | None = None,
) -> MemoryListResult:
    """
    List episodes with cursor-based pagination.

    Args:
        driver: Neo4j driver
        group_id: Group ID for filtering
        scope: Memory scope
        scope_id: Scope identifier
        limit: Maximum episodes to return
        cursor: ISO timestamp string for cursor (fetch episodes before this time)
        category: Optional category filter

    Returns:
        MemoryListResult with episodes and pagination info
    """
    # Parse cursor as datetime or use now
    if cursor:
        try:
            reference_time = datetime.fromisoformat(cursor)
            # Subtract 1 microsecond to exclude the episode at exactly cursor time.
            reference_time = reference_time - timedelta(microseconds=1)
        except ValueError:
            reference_time = utc_now()
    else:
        reference_time = utc_now()

    # Always use our custom query to get usage stats (category=None for unfiltered)
    episodes_raw, has_more = await fetch_episodes_filtered(
        driver, group_id, limit, reference_time, category
    )

    # Convert to MemoryEpisode objects
    episodes = convert_raw_episodes(episodes_raw, scope, scope_id)

    # Calculate cursor for next page
    next_cursor = None
    if episodes and has_more:
        # Use the valid_at of the last episode as cursor
        next_cursor = episodes[-1].valid_at.isoformat()

    return MemoryListResult(
        episodes=episodes,
        total=len(episodes),
        cursor=next_cursor,
        has_more=has_more,
    )
