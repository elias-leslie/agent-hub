"""Episode retrieval queries for context injection."""

import logging
import re
from typing import Any

from .context_injector_blocks_helpers import episode_to_result
from .embedder import get_embedder
from .memory_utils import build_group_id
from .repository import TIER_MAP, MemoryRepository, get_memory_repository
from .service import MemoryScope

logger = logging.getLogger(__name__)
_REFERENCE_MIN_SCORE = 0.2
_REFERENCE_SEARCH_LIMIT = 8
_REFERENCE_TOP_K = 3
_TOKEN_PATTERN = re.compile(r"[a-z0-9_./-]{3,}")


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    """Convert a Memory ORM object to a dict using MemoryRepository._to_dict."""
    return MemoryRepository._to_dict(mem)


async def get_episodes_by_tier(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get episodes by injection_tier field.

    This is the tier-first query method that replaces keyword matching.

    Args:
        tier: The injection tier (mandate/guardrail/reference)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of episode dicts with uuid, content, created_at, etc.
    """
    repo = get_memory_repository()
    group_id = build_group_id(scope, scope_id)

    try:
        memories = await repo.list_by_scope_and_tier(
            tier=tier,
            group_id=group_id,
            status="active",
        )
        return [_memory_to_dict(m) for m in memories]
    except Exception as e:
        logger.warning("Failed to get episodes by tier %s: %s", tier, e)
        return []


async def get_auto_inject_references(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference-tier episodes with auto_inject=true.

    These are references that should be injected like mandates/guardrails,
    but are categorized separately for organizational purposes.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of auto-inject reference episode dicts
    """
    repo = get_memory_repository()
    group_id = build_group_id(scope, scope_id)

    try:
        memories = await repo.list_by_scope_and_tier(
            tier="reference",
            auto_inject=True,
            group_id=group_id,
            status="active",
        )
        return [_memory_to_dict(m) for m in memories]
    except Exception as e:
        logger.warning("Failed to get auto-inject references: %s", e)
        return []


async def build_reference_toon_index(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[tuple[str, str | None, str, bool]]:
    """
    Get all reference-tier episodes for TOON index generation.

    Returns list of (uuid, summary, content, pinned) tuples for TOON formatting.
    Summary is used for display; content is fallback only.
    Pinned items are expanded to full content in format_context_with_reference_index.
    """
    episodes = await get_episodes_by_tier("reference", scope, scope_id)
    return [
        (ep.get("uuid", ""), ep.get("summary"), ep.get("content", ""), ep.get("pinned", False))
        for ep in episodes
        if ep.get("uuid") and ep.get("content")
    ]


def _tokenize(text: str) -> set[str]:
    return {match.group(0) for match in _TOKEN_PATTERN.finditer(text.lower())}


def _reference_exact_boost(query_terms: set[str], candidate: dict[str, Any]) -> float:
    haystack = " ".join(
        str(candidate.get(field) or "") for field in ("name", "summary", "content")
    ).lower()
    if not haystack or not query_terms:
        return 0.0
    candidate_terms = _tokenize(haystack)
    overlap = len(query_terms & candidate_terms)
    if overlap == 0:
        return 0.0
    return min(0.35, overlap * 0.08)


def _scope_bonus(scope: MemoryScope) -> float:
    return 0.12 if scope == MemoryScope.PROJECT else 0.0


async def get_query_relevant_references(
    query: str,
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    limit: int = _REFERENCE_TOP_K,
) -> list[dict[str, Any]]:
    """Select a small set of query-relevant references for direct injection."""
    if not query.strip():
        return []

    embedder = get_embedder()
    repo = get_memory_repository()
    query_embedding = await embedder.embed(query)
    query_terms = _tokenize(query)

    ranked: dict[str, tuple[float, dict[str, Any]]] = {}
    for scope, scope_id in scopes_to_query:
        group_id = build_group_id(scope, scope_id)
        semantic_rows = await repo.semantic_search(
            query_embedding,
            group_id=group_id,
            tier=TIER_MAP["reference"],
            limit=_REFERENCE_SEARCH_LIMIT,
            min_score=_REFERENCE_MIN_SCORE,
        )
        text_rows = [
            MemoryRepository._to_dict(mem)
            for mem in await repo.text_search(
                query,
                group_id=group_id,
                category="reference",
                limit=_REFERENCE_SEARCH_LIMIT,
            )
        ]

        for row in [*semantic_rows, *text_rows]:
            uuid = str(row.get("id") or row.get("uuid") or "")
            if not uuid:
                continue
            semantic_score = float(row.get("relevance_score") or 0.0)
            score = semantic_score + _reference_exact_boost(query_terms, row) + _scope_bonus(scope)
            if row.get("pinned"):
                score += 0.05
            current = ranked.get(uuid)
            candidate = dict(row)
            candidate["uuid"] = uuid
            candidate["score"] = score
            candidate["relevance_score"] = score
            if current is None or score > current[0]:
                ranked[uuid] = (score, candidate)

    winners = sorted(ranked.values(), key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in winners[:limit]]


async def get_query_relevant_references_as_search_results(
    query: str,
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    limit: int = _REFERENCE_TOP_K,
) -> list[dict[str, Any]]:
    """Return direct-injection reference candidates as MemorySearchResult payloads."""
    rows = await get_query_relevant_references(query, scopes_to_query, limit=limit)
    results: list[dict[str, Any]] = []
    for row in rows:
        result = episode_to_result(row)
        if result is None:
            continue
        result.relevance_score = float(row.get("relevance_score") or result.relevance_score)
        result.scope = MemoryScope(row.get("scope") or "global")
        results.append(result.model_dump())
    return results
