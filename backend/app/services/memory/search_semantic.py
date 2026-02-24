"""
Semantic search operations using PostgreSQL pgvector search.

Handles semantic search with deduplication and validation.
"""

import logging
from datetime import datetime
from typing import Any

from .embedder import get_embedder
from .memory_models import MemoryScope, MemorySearchResult, MemorySource
from .repository import get_memory_repository

logger = logging.getLogger(__name__)


def _create_search_result(
    result: dict[str, Any], scope: MemoryScope
) -> MemorySearchResult:
    """Create a single search result from a repository result dict."""
    uuid_val = result.get("id") or result.get("uuid", "")
    content = result.get("content", "")
    created = result.get("created_at")
    created_dt = created if isinstance(created, datetime) else datetime.now()
    score = float(result.get("relevance_score", 0.0))

    return MemorySearchResult(
        uuid=str(uuid_val),
        content=content,
        source=MemorySource.CHAT,
        relevance_score=score,
        created_at=created_dt,
        facts=[content] if content else [],
        scope=scope,
        pinned=result.get("pinned", False),
        tags=result.get("tags") or [],
    )


async def search_memory(
    group_id: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    query: str = "",
    limit: int = 10,
    min_score: float = 0.0,
) -> list[MemorySearchResult]:
    """
    Search memory for relevant episodes and facts.

    Uses pgvector cosine similarity via MemoryRepository.

    Args:
        group_id: Group ID to search within (None = search all groups).
        scope: Memory scope for tagging results.
        query: Search query text.
        limit: Maximum number of results.
        min_score: Minimum relevance score threshold.
    """
    embedder = get_embedder()
    query_vec = await embedder.embed(query)

    repo = get_memory_repository()
    results = await repo.semantic_search(
        query_vec,
        group_id=group_id,
        limit=limit * 3,
        min_score=min_score,
    )

    # Deduplicate and limit
    search_results: list[MemorySearchResult] = []
    seen_uuids: set[str] = set()
    valid_uuids: list[str] = []

    for result in results:
        uuid_str = str(result.get("id") or result.get("uuid", ""))
        if uuid_str in seen_uuids:
            continue

        seen_uuids.add(uuid_str)
        search_results.append(_create_search_result(result, scope))
        valid_uuids.append(uuid_str)

        if len(search_results) >= limit:
            break

    if valid_uuids:
        await repo.increment_loaded(valid_uuids)

    return search_results
