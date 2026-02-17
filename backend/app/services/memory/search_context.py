"""
Context retrieval operations for LLM prompt injection.

Extracts relevant facts, entities, and episodes for a given query.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graphiti_core import Graphiti
    from graphiti_core.edges import EntityEdge
else:
    Graphiti = None
    EntityEdge = None

from .memory_models import MemoryContext, MemoryScope, MemorySearchResult
from .memory_queries import update_access_time
from .search_helpers import build_search_result_from_edge, extract_entity_names, extract_facts

logger = logging.getLogger(__name__)


def _build_episodes_from_edges(
    edges: list["EntityEdge"], scope: MemoryScope, max_episodes: int = 5
) -> list[MemorySearchResult]:
    """Build episode search results from edges."""
    return [build_search_result_from_edge(edge, scope) for edge in edges[:max_episodes]]


async def get_context_for_query(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    query: str,
    max_facts: int = 10,
    max_entities: int = 5,
) -> MemoryContext:
    """Get relevant context for a query to inject into LLM prompts."""
    edges: Any = await graphiti.search(
        query=query, group_ids=[group_id], num_results=max_facts + max_entities
    )

    facts = extract_facts(edges, max_facts)
    entities = extract_entity_names(edges, max_entities)
    episodes = _build_episodes_from_edges(edges, scope)

    if edges:
        await update_access_time(graphiti.driver, [e.uuid for e in edges])

    return MemoryContext(
        query=query,
        relevant_facts=facts,
        relevant_entities=entities,
        episodes=episodes,
    )
