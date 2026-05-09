"""
Common helpers for search operations.

Provides shared utilities for dict-based result processing, score filtering,
and category mapping. Works with dict results from MemoryRepository.
"""

from datetime import datetime
from typing import Any

from .applicability import normalize_applicability, normalize_context_kind
from .memory_models import MemoryCategory, MemoryScope, MemorySearchResult, MemorySource
from .repository import TIER_REVERSE


def get_result_score(result: dict[str, Any]) -> float:
    """Extract relevance score from a search result dict."""
    return float(result.get("relevance_score", 0.0))


def filter_by_score(results: list[dict[str, Any]], min_score: float) -> list[dict[str, Any]]:
    """Filter search results by minimum relevance score."""
    return [r for r in results if get_result_score(r) >= min_score]


_TIER_TO_CATEGORY = {
    "mandate": MemoryCategory.MANDATE,
    "guardrail": MemoryCategory.GUARDRAIL,
    "reference": MemoryCategory.REFERENCE,
    "archive": MemoryCategory.ARCHIVE,
}


def map_tier_to_category(tier: str | int | None) -> MemoryCategory:
    """Map injection tier (string or int) to memory category."""
    if isinstance(tier, int):
        tier = TIER_REVERSE.get(tier, "reference")
    return _TIER_TO_CATEGORY.get(tier or "", MemoryCategory.REFERENCE)


def build_search_result_from_dict(
    result: dict[str, Any],
    scope: MemoryScope,
    category: MemoryCategory | None = None,
) -> MemorySearchResult:
    """Build a MemorySearchResult from a repository search result dict."""
    # Determine tier-based category if not explicitly provided
    if category is None:
        tier = result.get("tier")
        category = map_tier_to_category(tier)

    content = result.get("content", "")
    created_at = result.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = datetime.now()

    uuid_val = result.get("id") or result.get("uuid", "")
    uuid_str = str(uuid_val)

    return MemorySearchResult(
        uuid=uuid_str,
        content=content,
        compact_content=result.get("compact_content"),
        summary=result.get("summary"),
        source=MemorySource.CHAT,
        relevance_score=get_result_score(result),
        created_at=created_at,
        facts=[content] if content else [],
        scope=scope,
        category=category,
        pinned=result.get("pinned", False),
        tags=result.get("tags") or [],
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


def extract_entity_names_from_results(results: list[dict[str, Any]], max_entities: int) -> list[str]:
    """Extract unique entity-like names from search results (name field)."""
    entities: list[str] = []
    seen_names: set[str] = set()

    for result in results[:max_entities * 2]:
        name = result.get("name")
        if name and name not in seen_names:
            entities.append(name)
            seen_names.add(name)
        if len(entities) >= max_entities:
            break

    return entities


def extract_facts_from_results(results: list[dict[str, Any]], max_facts: int) -> list[str]:
    """Extract fact/content strings from search results."""
    facts: list[str] = []

    for result in results[:max_facts]:
        content = result.get("content")
        if content:
            facts.append(content)

    return facts
