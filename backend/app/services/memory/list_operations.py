"""List and pagination operations for memory episodes."""


from .episode_converters import convert_raw_episodes
from .memory_models import (
    MemoryCategory,
    MemoryListResult,
    MemoryScope,
)
from .repository import get_memory_repository


async def list_episodes_paginated(
    group_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
    limit: int = 50,
    cursor: str | None = None,
    category: MemoryCategory | None = None,
) -> MemoryListResult:
    """
    List episodes with cursor-based pagination.

    Args:
        group_id: Group ID for filtering (None = all groups)
        scope: Memory scope
        scope_id: Scope identifier
        limit: Maximum episodes to return
        cursor: ISO timestamp string for cursor (fetch episodes before this time)
        category: Optional category filter

    Returns:
        MemoryListResult with episodes and pagination info
    """
    repo = get_memory_repository()
    cat_value = category.value if category else None

    # all_groups path passes group_id=None; do not force scope filter in that case.
    query_scope = scope.value if scope and group_id is not None else None
    query_scope_id = scope_id if query_scope else None

    result = await repo.list_paginated(
        group_id=group_id,
        scope=query_scope,
        scope_id=query_scope_id,
        category=cat_value,
        limit=limit,
        cursor=cursor,
    )

    memories = result["memories"]
    has_more = result["has_more"]

    # Convert Memory ORM objects to MemoryEpisode models.
    # Scope/scope_id are derived per row from group_id when present.
    episodes = convert_raw_episodes(memories, scope=scope, scope_id=scope_id)

    # Calculate cursor for next page
    next_cursor = result.get("cursor") if has_more else None

    return MemoryListResult(
        episodes=episodes,
        total=len(episodes),
        cursor=next_cursor,
        has_more=has_more,
    )
