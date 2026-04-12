"""Episode retrieval queries for context injection."""

import logging
import re
from typing import Any

from .episode_validation import EpisodeValidator
from .memory_utils import build_group_id
from .repository import MemoryRepository, get_memory_repository
from .service import MemoryScope

logger = logging.getLogger(__name__)
_REFERENCE_MIN_SCORE = 0.2
_REFERENCE_SEARCH_LIMIT = 8
_REFERENCE_TOP_K = 3
_TOKEN_PATTERN = re.compile(r"[a-z0-9_./-]{3,}")


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    """Convert a Memory ORM object to a dict using MemoryRepository._to_dict."""
    return MemoryRepository._to_dict(mem)


def _is_reference_candidate(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("is_session_summary"):
        return False

    content = str(candidate.get("content") or "")
    source_description = str(candidate.get("source_description") or "")
    if EpisodeValidator.validate_reusability_simple(content):
        return False
    return "session_summary" not in source_description


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


async def get_pinned_episodes_by_tier(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get pinned episodes for a tier.

    Pinned items should always be present in context whenever memory and the
    corresponding category are enabled, even when they would not normally be
    selected by a narrower retrieval path.
    """
    repo = get_memory_repository()
    group_id = build_group_id(scope, scope_id)

    try:
        memories = await repo.list_by_scope_and_tier(
            tier=tier,
            pinned=True,
            group_id=group_id,
            status="active",
        )
        return [_memory_to_dict(m) for m in memories]
    except Exception as e:
        logger.warning("Failed to get pinned episodes for tier %s: %s", tier, e)
        return []


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

    from .embedder import get_embedder_or_none
    from .repository import TIER_MAP

    repo = get_memory_repository()
    query_terms = _tokenize(query)
    embedder = get_embedder_or_none("progressive context reference selection")
    query_embedding: list[float] | None = None
    if embedder is not None:
        try:
            query_embedding = await embedder.embed(query)
        except Exception:
            logger.warning(
                "Reference semantic retrieval unavailable for query=%s; using text-only selection",
                query[:80],
                exc_info=True,
            )

    ranked: dict[str, tuple[float, dict[str, Any]]] = {}

    # Parallelize per-scope queries with asyncio.gather
    import asyncio

    async def _fetch_scope(
        scope: MemoryScope, scope_id: str | None
    ) -> list[tuple[MemoryScope, dict[str, Any]]]:
        gid = build_group_id(scope, scope_id)
        semantic_rows: list[dict[str, Any]] = []
        if query_embedding is not None:
            semantic_rows = await repo.semantic_search(
                query_embedding,
                group_id=gid,
                tier=TIER_MAP["reference"],
                limit=_REFERENCE_SEARCH_LIMIT,
                min_score=_REFERENCE_MIN_SCORE,
            )
        text_rows = [
            MemoryRepository._to_dict(mem)
            for mem in await repo.text_search(
                query,
                group_id=gid,
                category="reference",
                limit=_REFERENCE_SEARCH_LIMIT,
            )
        ]
        return [(scope, row) for row in [*semantic_rows, *text_rows]]

    scope_results = await asyncio.gather(
        *(_fetch_scope(scope, scope_id) for scope, scope_id in scopes_to_query)
    )

    for scope_rows in scope_results:
        for scope, row in scope_rows:
            uuid = str(row.get("id") or row.get("uuid") or "")
            if not uuid or not _is_reference_candidate(row):
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
    from .context_injector_blocks_helpers import episode_to_result

    rows = await get_query_relevant_references(query, scopes_to_query, limit=limit)
    results: list[dict[str, Any]] = []
    for row in rows:
        result = episode_to_result(row)
        if result is None:
            continue
        result.relevance_score = float(row.get("relevance_score") or result.relevance_score)
        result.scope = MemoryScope(row.get("scope") or "global")
        payload = result.model_dump()
        payload["trigger_task_types"] = list(row.get("trigger_task_types") or [])
        payload["trigger_phases"] = list(row.get("trigger_phases") or [])
        results.append(payload)
    return results
