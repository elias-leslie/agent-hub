"""Search and context operations for memory service."""

from typing import Any

from graphiti_core import Graphiti

from .episode_converters import convert_raw_episodes
from .memory_models import (
    MemoryCategory,
    MemoryContext,
    MemoryEpisode,
    MemoryScope,
    MemorySearchResult,
)
from .memory_queries import text_search_episodes
from .search_operations import (
    get_context_for_query,
    get_patterns_and_gotchas,
    get_session_history,
    search_memory,
)


async def semantic_search(
    graphiti: Graphiti,
    group_id: str,
    scope: MemoryScope,
    query: str,
    limit: int,
    min_score: float,
) -> list[MemorySearchResult]:
    """Search memory for relevant episodes using semantic/vector search."""
    return await search_memory(graphiti, group_id, scope, query, limit, min_score)


async def text_search(
    driver: Any,
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    query: str,
    limit: int,
    category: MemoryCategory | None,
) -> list[MemoryEpisode]:
    """Text-based substring search on episode content."""
    episodes_raw = await text_search_episodes(driver, group_id, query, limit, category)
    return convert_raw_episodes(episodes_raw, scope, scope_id)


async def get_query_context(
    graphiti: Graphiti,
    group_id: str,
    scope: MemoryScope,
    query: str,
    max_facts: int,
    max_entities: int,
) -> MemoryContext:
    """Get relevant context for a query to inject into LLM prompts."""
    return await get_context_for_query(graphiti, group_id, scope, query, max_facts, max_entities)


async def get_patterns_gotchas(
    graphiti: Graphiti,
    group_id: str,
    scope: MemoryScope,
    query: str,
    num_results: int,
    min_score: float,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Get relevant patterns and gotchas for a query."""
    return await get_patterns_and_gotchas(graphiti, group_id, scope, query, num_results, min_score)


async def get_history(
    graphiti: Graphiti,
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    num_sessions: int,
) -> list[MemoryEpisode]:
    """Get recent session recommendations and insights."""
    return await get_session_history(graphiti, group_id, scope, scope_id, num_sessions)
