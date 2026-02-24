"""
Pattern and gotcha search operations.

Retrieves coding standards and troubleshooting guides with category filtering
using PostgreSQL pgvector search.
"""

import logging
from typing import Any

from .embedder import get_embedder
from .memory_models import MemoryCategory, MemoryScope, MemorySearchResult
from .repository import get_memory_repository
from .search_helpers import build_search_result_from_dict, get_result_score, map_tier_to_category

logger = logging.getLogger(__name__)


def _filter_by_category(
    results: list[dict[str, Any]],
    scope: MemoryScope,
    target_category: MemoryCategory,
    min_score: float,
    num_results: int,
) -> tuple[list[MemorySearchResult], list[str]]:
    """
    Filter search results by category and build results.

    Returns tuple of (results, uuids).
    """
    filtered: list[MemorySearchResult] = []
    uuids: list[str] = []

    for result in results:
        if get_result_score(result) < min_score:
            continue

        tier = result.get("tier")
        category = map_tier_to_category(tier)

        if category == target_category:
            filtered.append(build_search_result_from_dict(result, scope, category))
            uuid_str = str(result.get("id") or result.get("uuid", ""))
            uuids.append(uuid_str)

            if len(filtered) >= num_results:
                break

    return filtered, uuids


async def get_patterns_and_gotchas(
    graphiti: object = None,
    group_id: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    query: str = "",
    num_results: int = 10,
    min_score: float = 0.5,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Get patterns (REFERENCE) and gotchas (GUARDRAIL) for a query.

    Args:
        graphiti: Unused (kept for backward compatibility). Pass None.
        group_id: Group ID to search within.
        scope: Memory scope for tagging results.
        query: Search query text.
        num_results: Maximum results per category.
        min_score: Minimum relevance score threshold.
    """
    embedder = get_embedder()
    repo = get_memory_repository()

    # Embed both query variants
    pattern_vec = await embedder.embed(f"coding standard pattern: {query}")
    gotcha_vec = await embedder.embed(f"troubleshooting gotcha pitfall: {query}")

    pattern_results = await repo.semantic_search(
        pattern_vec,
        group_id=group_id,
        limit=num_results * 2,
        min_score=min_score,
    )

    gotcha_results = await repo.semantic_search(
        gotcha_vec,
        group_id=group_id,
        limit=num_results * 2,
        min_score=min_score,
    )

    patterns, pattern_uuids = _filter_by_category(
        pattern_results, scope, MemoryCategory.REFERENCE, min_score, num_results
    )
    gotchas, gotcha_uuids = _filter_by_category(
        gotcha_results, scope, MemoryCategory.GUARDRAIL, min_score, num_results
    )

    all_uuids = pattern_uuids + gotcha_uuids
    if all_uuids:
        await repo.increment_loaded(all_uuids)

    return patterns, gotchas
