"""Search and context operations for memory service.

Delegates to search_operations submodules that use MemoryRepository + pgvector.
"""

from .episode_converters import convert_raw_episodes
from .memory_models import (
    MemoryCategory,
    MemoryContext,
    MemoryEpisode,
    MemoryScope,
    MemorySearchResult,
)
from .repository import get_memory_repository
from .search_operations import (
    get_context_for_query,
    get_patterns_and_gotchas,
    get_session_history,
    search_memory,
)


async def semantic_search(
    group_id: str | None,
    scope: MemoryScope,
    query: str,
    limit: int,
    min_score: float,
) -> list[MemorySearchResult]:
    """Search memory for relevant episodes using semantic/vector search."""
    return await search_memory(group_id, scope, query, limit, min_score)


async def text_search(
    group_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
    query: str,
    limit: int,
    category: MemoryCategory | None,
) -> list[MemoryEpisode]:
    """Text-based substring search on episode content."""
    repo = get_memory_repository()
    cat_value = category.value if category else None
    # all_groups path passes group_id=None; do not force scope filter in that case.
    query_scope = scope.value if scope and group_id is not None else None
    memories = await repo.text_search(
        query, group_id=group_id, scope=query_scope, category=cat_value, limit=limit
    )
    return convert_raw_episodes(memories, scope=scope, scope_id=scope_id)


async def get_query_context(
    group_id: str | None,
    scope: MemoryScope,
    query: str,
    max_facts: int,
    max_entities: int,
) -> MemoryContext:
    """Get relevant context for a query to inject into LLM prompts."""
    return await get_context_for_query(group_id, scope, query, max_facts, max_entities)


async def get_patterns_gotchas(
    group_id: str | None,
    scope: MemoryScope,
    query: str,
    num_results: int,
    min_score: float,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Get relevant patterns and gotchas for a query."""
    return await get_patterns_and_gotchas(group_id, scope, query, num_results, min_score)


async def get_history(
    group_id: str | None,
    scope: MemoryScope,
    scope_id: str | None,
    num_sessions: int,
) -> list[MemoryEpisode]:
    """Get recent session recommendations and insights."""
    return await get_session_history(group_id, scope, scope_id, num_sessions)
