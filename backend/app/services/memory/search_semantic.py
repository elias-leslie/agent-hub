"""
Semantic search operations using PostgreSQL pgvector search.

Handles hybrid search (semantic + text) with deduplication and validation.
"""

import logging
from datetime import datetime
from typing import Any

from ._repo_helpers import to_dict
from .applicability import normalize_applicability, normalize_context_kind
from .embedder import get_embedder_or_none
from .memory_models import MemoryCategory, MemoryScope, MemorySearchResult, MemorySource
from .repository import TIER_REVERSE, get_memory_repository

logger = logging.getLogger(__name__)

# Text match bonus added to semantic score for keyword hits
_TEXT_MATCH_BONUS = 0.20


def _tier_to_category(result: dict[str, Any]) -> MemoryCategory | None:
    """Derive MemoryCategory from the numeric tier column in a result dict."""
    tier_val = result.get("tier")
    if tier_val is None:
        return None
    tier_name = TIER_REVERSE.get(int(tier_val))
    if tier_name is None:
        return None
    try:
        return MemoryCategory(tier_name)
    except ValueError:
        return None


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
        compact_content=result.get("compact_content"),
        source=MemorySource.CHAT,
        relevance_score=score,
        created_at=created_dt,
        facts=[content] if content else [],
        scope=scope,
        category=_tier_to_category(result),
        pinned=result.get("pinned", False),
        tags=result.get("tags") or [],
        summary=result.get("summary"),
        review_status=str(result.get("review_status") or "pending"),
        sensitivity_tier=str(result.get("sensitivity_tier") or "normal"),
        token_count=int(result.get("token_count") or 0),
        last_reviewed_at=result.get("last_reviewed_at"),
        context_kind=normalize_context_kind(
            result.get("context_kind"),
            memory_type=result.get("memory_type"),
            tier=result.get("tier"),
        ),
        applicability=normalize_applicability(result.get("applicability")),
    )


async def search_memory(
    group_id: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    query: str = "",
    limit: int = 10,
    min_score: float = 0.0,
    category: str | None = None,
) -> list[MemorySearchResult]:
    """
    Hybrid search: semantic similarity + text keyword matching.

    Runs both pgvector cosine similarity and ILIKE text search in parallel,
    merges results with text matches boosted, deduplicates, and returns top N.

    Args:
        group_id: Group ID to search within (None = search all groups).
        scope: Memory scope for tagging results.
        query: Search query text.
        limit: Maximum number of results.
        min_score: Minimum relevance score threshold.
        category: Optional tier filter (mandate, guardrail, reference).
    """
    from .repository import TIER_MAP

    repo = get_memory_repository()

    tier_filter = TIER_MAP.get(category) if category else None

    # Run text search for keyword boosting and as a read-side fallback when
    # semantic embeddings are temporarily unavailable.
    text_hit_uuids: set[str] = set()
    text_matches: list[Any] = []
    try:
        text_matches = await repo.text_search(
            query,
            group_id=group_id,
            category=category,
            limit=limit * 3,
        )
        for mem in text_matches:
            text_hit_uuids.add(str(mem.id))
    except Exception:
        logger.debug("Text search fallback failed, using semantic only", exc_info=True)

    semantic_results: list[dict[str, Any]] = []
    embedder = get_embedder_or_none("memory search")
    if embedder is not None:
        try:
            query_vec = await embedder.embed(query)
            semantic_results = await repo.semantic_search(
                query_vec,
                group_id=group_id,
                tier=tier_filter,
                limit=limit * 3,
                min_score=min_score,
            )
        except Exception:
            logger.warning(
                "Semantic memory search unavailable for query=%s; using text-only results",
                query[:80],
                exc_info=True,
            )

    # Merge: boost semantic scores for text hits, collect text-only hits
    best_scores: dict[str, tuple[float, dict[str, Any]]] = {}

    for result in semantic_results:
        uuid_str = str(result.get("id") or result.get("uuid", ""))
        score = float(result.get("relevance_score", 0.0))
        if uuid_str in text_hit_uuids:
            score = min(score + _TEXT_MATCH_BONUS, 1.0)
        if uuid_str not in best_scores or score > best_scores[uuid_str][0]:
            result_copy = dict(result)
            result_copy["relevance_score"] = score
            best_scores[uuid_str] = (score, result_copy)

    # Add text-only hits not in semantic results (with a base score)
    for mem in text_matches:
        uuid_str = str(mem.id)
        if uuid_str not in best_scores:
            mem_dict = to_dict(mem)
            mem_dict["relevance_score"] = _TEXT_MATCH_BONUS
            best_scores[uuid_str] = (_TEXT_MATCH_BONUS, mem_dict)

    # Sort by score descending, take top N
    sorted_results = sorted(best_scores.values(), key=lambda x: x[0], reverse=True)

    search_results: list[MemorySearchResult] = []
    valid_uuids: list[str] = []

    for _score, result in sorted_results:
        if len(search_results) >= limit:
            break
        sr = _create_search_result(result, scope)
        search_results.append(sr)
        valid_uuids.append(sr.uuid)

    if valid_uuids:
        await repo.increment_loaded(valid_uuids)

    return search_results
