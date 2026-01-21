"""
Memory selection for context injection.

Implements Decision d6: Score-based selection with minimum relevance threshold.
- All memories compete on final_score
- Items above threshold are included (no arbitrary caps)
- High-scoring guardrails can beat low-scoring mandates
- Tier multipliers applied during scoring, not hard filtering
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .scoring import MemoryScore, MemoryScoreInput, score_memory
from .service import MemorySearchResult
from .variants import VariantConfig, get_variant_config

logger = logging.getLogger(__name__)


@dataclass
class ScoredMemory:
    """A memory item with its computed score."""

    memory: MemorySearchResult
    score: MemoryScore
    tier: str  # "mandate", "guardrail", or "reference"


def score_search_result(
    result: MemorySearchResult,
    tier: str,
    config: VariantConfig,
    has_tag_match: bool = False,
    now: datetime | None = None,
) -> ScoredMemory:
    """
    Score a MemorySearchResult using multi-factor scoring.

    Args:
        result: The search result to score
        tier: Memory tier ("mandate", "guardrail", "reference")
        config: Variant configuration
        has_tag_match: Whether the memory matches agent mandate_tags
        now: Current time for recency calculation

    Returns:
        ScoredMemory with score details
    """
    # Build score input from search result
    input_data = MemoryScoreInput(
        semantic_similarity=result.relevance_score,
        confidence=getattr(result, "confidence", 50.0),  # Default 50 if not set
        loaded_count=getattr(result, "loaded_count", 0),
        referenced_count=getattr(result, "referenced_count", 0),
        created_at=result.created_at,
        last_used_at=getattr(result, "last_used_at", None),
        tier=tier,
        has_tag_match=has_tag_match,
    )

    score = score_memory(input_data, config, now)

    return ScoredMemory(
        memory=result,
        score=score,
        tier=tier,
    )


def select_memories(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
    config: VariantConfig,
    tag_matches: set[str] | None = None,
    now: datetime | None = None,
) -> tuple[list[ScoredMemory], dict[str, Any]]:
    """
    Select memories using score-based ranking with threshold filtering.

    Implements Decision d6:
    - All memories compete on final_score
    - Items above min_relevance_threshold are included
    - High-scoring guardrails can beat low-scoring mandates
    - No arbitrary caps on tokens or item counts

    Args:
        mandates: Mandate search results
        guardrails: Guardrail search results
        references: Reference search results
        config: Variant configuration
        tag_matches: Set of UUIDs matching agent mandate_tags (get tag boost)
        now: Current time for recency calculation

    Returns:
        Tuple of (selected_memories sorted by score, debug_info)
    """
    tag_matches = tag_matches or set()

    # Score all memories
    scored: list[ScoredMemory] = []

    for m in mandates:
        sm = score_search_result(
            m, "mandate", config,
            has_tag_match=m.uuid in tag_matches,
            now=now,
        )
        scored.append(sm)

    for g in guardrails:
        sm = score_search_result(
            g, "guardrail", config,
            has_tag_match=g.uuid in tag_matches,
            now=now,
        )
        scored.append(sm)

    for r in references:
        sm = score_search_result(
            r, "reference", config,
            has_tag_match=r.uuid in tag_matches,
            now=now,
        )
        scored.append(sm)

    # Sort by final score descending
    scored.sort(key=lambda x: x.score.final_score, reverse=True)

    # Filter by threshold
    selected = [s for s in scored if s.score.passes_threshold]

    # Build debug info
    debug_info = {
        "total_scored": len(scored),
        "selected_count": len(selected),
        "threshold": config.min_relevance_threshold,
        "excluded_count": len(scored) - len(selected),
        "by_tier": {
            "mandates": len([s for s in selected if s.tier == "mandate"]),
            "guardrails": len([s for s in selected if s.tier == "guardrail"]),
            "references": len([s for s in selected if s.tier == "reference"]),
        },
    }

    logger.info(
        "Selected %d/%d memories (threshold=%.2f): mandates=%d guardrails=%d refs=%d",
        len(selected),
        len(scored),
        config.min_relevance_threshold,
        debug_info["by_tier"]["mandates"],
        debug_info["by_tier"]["guardrails"],
        debug_info["by_tier"]["references"],
    )

    return selected, debug_info


def high_scoring_guardrail_beats_mandate(
    guardrail: MemorySearchResult,
    mandate: MemorySearchResult,
    config: VariantConfig,
) -> bool:
    """
    Check if a guardrail can beat a mandate based on scoring.

    This validates Decision d6: High-scoring guardrails can beat low-scoring mandates.
    The tier multiplier is applied during scoring, but doesn't guarantee mandates
    always win.

    Args:
        guardrail: A guardrail memory
        mandate: A mandate memory
        config: Variant configuration

    Returns:
        True if guardrail scores higher than mandate
    """
    g_scored = score_search_result(guardrail, "guardrail", config)
    m_scored = score_search_result(mandate, "mandate", config)

    return g_scored.score.final_score > m_scored.score.final_score


def select_for_context(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
    variant: str = "BASELINE",
    tag_matches: set[str] | None = None,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult], dict[str, Any]]:
    """
    Select memories for context injection, maintaining tier separation.

    This is a convenience function that returns selected items grouped by tier
    for compatibility with existing context injection code.

    Args:
        mandates: Mandate search results
        guardrails: Guardrail search results
        references: Reference search results
        variant: Variant name
        tag_matches: Set of UUIDs matching agent mandate_tags

    Returns:
        Tuple of (selected_mandates, selected_guardrails, selected_references, debug_info)
    """
    config = get_variant_config(variant)

    selected, debug_info = select_memories(
        mandates, guardrails, references,
        config, tag_matches,
    )

    # Regroup by tier
    selected_mandates = [s.memory for s in selected if s.tier == "mandate"]
    selected_guardrails = [s.memory for s in selected if s.tier == "guardrail"]
    selected_references = [s.memory for s in selected if s.tier == "reference"]

    return selected_mandates, selected_guardrails, selected_references, debug_info
