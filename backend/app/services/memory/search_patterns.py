"""
Pattern and gotcha search operations.

Retrieves coding standards and troubleshooting guides with category filtering.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphiti_core import Graphiti
    from graphiti_core.edges import EntityEdge
else:
    Graphiti = None
    EntityEdge = None

from .memory_models import MemoryCategory, MemoryScope, MemorySearchResult, MemorySource
from .memory_queries import update_access_time
from .search_helpers import get_edge_score, map_tier_to_category

logger = logging.getLogger(__name__)


def _build_search_result(
    edge: "EntityEdge", scope: MemoryScope, category: MemoryCategory
) -> MemorySearchResult:
    """Build a MemorySearchResult from an edge."""
    return MemorySearchResult(
        uuid=edge.uuid,
        content=edge.fact or "",
        source=MemorySource.CHAT,
        relevance_score=get_edge_score(edge),
        created_at=edge.created_at,
        facts=[edge.fact] if edge.fact else [],
        scope=scope,
        category=category,
    )


def _filter_by_category(
    edges: list["EntityEdge"],
    scope: MemoryScope,
    target_category: MemoryCategory,
    min_score: float,
    num_results: int,
) -> tuple[list[MemorySearchResult], list[str]]:
    """
    Filter edges by category and build results.

    Returns tuple of (results, uuids).
    """
    results: list[MemorySearchResult] = []
    uuids: list[str] = []

    for edge in edges:
        if get_edge_score(edge) < min_score:
            continue

        tier = getattr(edge, "injection_tier", None)
        category = map_tier_to_category(tier)

        if category == target_category:
            results.append(_build_search_result(edge, scope, category))
            uuids.append(edge.uuid)

            if len(results) >= num_results:
                break

    return results, uuids


async def get_patterns_and_gotchas(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    query: str,
    num_results: int = 10,
    min_score: float = 0.5,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Get patterns (REFERENCE) and gotchas (GUARDRAIL) for a query."""
    pattern_edges = await graphiti.search(
        query=f"coding standard pattern: {query}",
        group_ids=[group_id],
        num_results=num_results * 2,
    )

    gotcha_edges = await graphiti.search(
        query=f"troubleshooting gotcha pitfall: {query}",
        group_ids=[group_id],
        num_results=num_results * 2,
    )

    patterns, pattern_uuids = _filter_by_category(
        pattern_edges, scope, MemoryCategory.REFERENCE, min_score, num_results
    )
    gotchas, gotcha_uuids = _filter_by_category(
        gotcha_edges, scope, MemoryCategory.GUARDRAIL, min_score, num_results
    )

    all_uuids = pattern_uuids + gotcha_uuids
    if all_uuids:
        await update_access_time(graphiti.driver, all_uuids)

    return patterns, gotchas
