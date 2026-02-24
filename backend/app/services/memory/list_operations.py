"""List and pagination operations for memory episodes."""


from .memory_models import (
    MemoryCategory,
    MemoryEpisode,
    MemoryListResult,
    MemoryScope,
    MemorySource,
)
from .repository import get_memory_repository
from .search_helpers import map_tier_to_category


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

    result = await repo.list_paginated(
        group_id=group_id,
        scope=scope.value if scope else None,
        scope_id=scope_id,
        category=cat_value,
        limit=limit,
        cursor=cursor,
    )

    memories = result["memories"]
    has_more = result["has_more"]

    # Convert Memory ORM objects to MemoryEpisode models
    episodes = []
    for mem in memories:
        episodes.append(
            MemoryEpisode(
                uuid=str(mem.id),
                name=mem.name or "",
                content=mem.content or "",
                source=MemorySource.CHAT,
                category=map_tier_to_category(mem.tier),
                scope=scope or MemoryScope.GLOBAL,
                scope_id=scope_id,
                source_description=mem.source_description or "",
                created_at=mem.created_at,
                valid_at=mem.valid_at or mem.created_at,
                entities=[],
                summary=mem.summary,
                loaded_count=mem.loaded_count,
                referenced_count=mem.referenced_count,
                helpful_count=mem.helpful_count,
                harmful_count=mem.harmful_count,
                utility_score=mem.utility_score,
                pinned=mem.pinned,
                tags=mem.tags or [],
            )
        )

    # Calculate cursor for next page
    next_cursor = None
    if episodes and has_more:
        next_cursor = episodes[-1].valid_at.isoformat()

    return MemoryListResult(
        episodes=episodes,
        total=len(episodes),
        cursor=next_cursor,
        has_more=has_more,
    )
