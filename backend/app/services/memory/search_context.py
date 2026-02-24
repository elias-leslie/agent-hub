"""
Context retrieval operations for LLM prompt injection.

Extracts relevant facts, entities, and episodes for a given query
using PostgreSQL pgvector search.
"""

import logging
from typing import Any

from .embedder import get_embedder
from .memory_models import MemoryContext, MemoryScope, MemorySearchResult
from .repository import get_memory_repository
from .search_helpers import (
    build_search_result_from_dict,
    extract_entity_names_from_results,
    extract_facts_from_results,
)

logger = logging.getLogger(__name__)


def _build_episodes_from_results(
    results: list[dict[str, Any]], scope: MemoryScope, max_episodes: int = 5
) -> list[MemorySearchResult]:
    """Build episode search results from repository result dicts."""
    return [build_search_result_from_dict(r, scope) for r in results[:max_episodes]]


async def get_context_for_query(
    graphiti: object = None,
    group_id: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    query: str = "",
    max_facts: int = 10,
    max_entities: int = 5,
) -> MemoryContext:
    """Get relevant context for a query to inject into LLM prompts.

    Args:
        graphiti: Unused (kept for backward compatibility). Pass None.
        group_id: Group ID to search within.
        scope: Memory scope for tagging results.
        query: Search query text.
        max_facts: Maximum number of facts to return.
        max_entities: Maximum number of entities to return.
    """
    embedder = get_embedder()
    query_vec = await embedder.embed(query)

    repo = get_memory_repository()
    results = await repo.semantic_search(
        query_vec,
        group_id=group_id,
        limit=max_facts + max_entities,
    )

    facts = extract_facts_from_results(results, max_facts)
    entities = extract_entity_names_from_results(results, max_entities)
    episodes = _build_episodes_from_results(results, scope)

    if results:
        uuids = [str(r.get("id") or r.get("uuid", "")) for r in results]
        await repo.increment_loaded(uuids)

    return MemoryContext(
        query=query,
        relevant_facts=facts,
        relevant_entities=entities,
        episodes=episodes,
    )
