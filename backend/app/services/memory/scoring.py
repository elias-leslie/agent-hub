"""
Multi-factor scoring for memory context injection.

Implements the scoring formula from Decision d1:
- semantic: 0.4 weight - semantic similarity to query
- usage: 0.3 weight - usage effectiveness (referenced/loaded)
- confidence: 0.2 weight - confidence score
- recency: 0.1 weight - recency decay

The final score determines which memories are injected into context.
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .variants import VariantConfig

logger = logging.getLogger(__name__)


@dataclass
class MemoryScoreInput:
    """Input data for scoring a memory item."""

    # Required fields
    semantic_similarity: float  # 0.0 - 1.0, from vector search
    confidence: float  # 0.0 - 100.0, from Graphiti confidence

    # Usage statistics (default to 0 if not tracked yet)
    loaded_count: int = 0  # Times injected into context
    referenced_count: int = 0  # Times cited by LLM

    # Recency (optional)
    created_at: datetime | None = None
    last_used_at: datetime | None = None

    # Tier information
    tier: str = "reference"  # "mandate", "guardrail", or "reference"

    # Optional: tag match for agent mandate_tags boost
    has_tag_match: bool = False


@dataclass
class MemoryScore:
    """Result of scoring a memory item."""

    final_score: float  # Combined weighted score (0.0 - 1.0+)
    semantic_component: float
    usage_component: float
    confidence_component: float
    recency_component: float
    tier_multiplier: float
    tag_boost: float
    passes_threshold: bool  # Whether score meets minimum threshold

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "final_score": round(self.final_score, 4),
            "semantic": round(self.semantic_component, 4),
            "usage": round(self.usage_component, 4),
            "confidence": round(self.confidence_component, 4),
            "recency": round(self.recency_component, 4),
            "tier_multiplier": self.tier_multiplier,
            "tag_boost": self.tag_boost,
            "passes": self.passes_threshold,
        }


def calculate_recency_decay(
    created_at: datetime | None,
    last_used_at: datetime | None,
    half_life_days: int,
    now: datetime | None = None,
) -> float:
    """
    Calculate recency decay score using exponential decay.

    Uses the more recent of created_at or last_used_at as the reference point.
    Returns 1.0 for fresh items, decaying towards 0.0 for older items.

    Args:
        created_at: When the memory was created
        last_used_at: When the memory was last used (cited)
        half_life_days: Days until value decays to 50%
        now: Current time (defaults to UTC now)

    Returns:
        Recency score between 0.0 and 1.0
    """
    if now is None:
        now = datetime.now(UTC)

    # Use the more recent timestamp
    reference_time = None
    if last_used_at is not None:
        reference_time = last_used_at
    if created_at is not None and (reference_time is None or created_at > reference_time):
        reference_time = created_at

    if reference_time is None:
        return 0.5  # Default to middle value if no timestamp

    # Ensure timezone awareness
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    # Calculate age in days
    age = now - reference_time
    age_days = age.total_seconds() / (24 * 3600)

    if age_days <= 0:
        return 1.0

    # Exponential decay: score = 0.5^(age/half_life)
    decay = math.pow(0.5, age_days / half_life_days)
    return max(0.0, min(1.0, decay))


def calculate_usage_effectiveness(loaded_count: int, referenced_count: int) -> float:
    """
    Calculate usage effectiveness score.

    Measures how often a memory is actually cited when injected.
    Higher score = more useful/referenced memory.

    Args:
        loaded_count: Times injected into context
        referenced_count: Times cited by LLM

    Returns:
        Effectiveness score between 0.0 and 1.0
    """
    if loaded_count <= 0:
        # Never loaded - assume 0.5 (neutral) as baseline
        return 0.5

    # Base effectiveness is reference ratio
    effectiveness = referenced_count / loaded_count

    # Cap at 1.0 (can't be more than 100% effective)
    return min(1.0, effectiveness)


def score_memory(
    input_data: MemoryScoreInput,
    config: VariantConfig,
    now: datetime | None = None,
) -> MemoryScore:
    """
    Score a memory item using multi-factor weighted scoring.

    Implements Decision d1: Multi-factor scoring with semantic (0.4), usage (0.3),
    confidence (0.2), and recency (0.1) weights.

    Args:
        input_data: Memory data to score
        config: Variant configuration with weights and thresholds
        now: Current time for recency calculation (defaults to UTC now)

    Returns:
        MemoryScore with component scores and final combined score
    """
    weights = config.scoring_weights
    tiers = config.tier_multipliers
    recency_config = config.recency_config

    # 1. Semantic component (already 0-1)
    semantic = max(0.0, min(1.0, input_data.semantic_similarity))

    # 2. Usage effectiveness component
    usage = calculate_usage_effectiveness(
        input_data.loaded_count,
        input_data.referenced_count,
    )

    # 3. Confidence component (normalize from 0-100 to 0-1)
    confidence = max(0.0, min(1.0, input_data.confidence / 100.0))

    # 4. Recency component (with tier-specific half-life)
    half_life = recency_config.reference_half_life_days
    if input_data.tier == "mandate":
        half_life = recency_config.mandate_half_life_days

    recency = calculate_recency_decay(
        input_data.created_at,
        input_data.last_used_at,
        half_life,
        now,
    )

    # Calculate weighted base score
    base_score = (
        semantic * weights.semantic
        + usage * weights.usage
        + confidence * weights.confidence
        + recency * weights.recency
    )

    # Apply tier multiplier
    tier_multiplier = tiers.reference
    if input_data.tier == "mandate":
        tier_multiplier = tiers.mandate
    elif input_data.tier == "guardrail":
        tier_multiplier = tiers.guardrail

    # Apply tag boost if applicable
    tag_boost = 1.0
    if input_data.has_tag_match:
        tag_boost = tiers.agent_tag_boost

    # Final score with multipliers
    final_score = base_score * tier_multiplier * tag_boost

    # Check threshold
    passes_threshold = final_score >= config.min_relevance_threshold

    return MemoryScore(
        final_score=final_score,
        semantic_component=semantic,
        usage_component=usage,
        confidence_component=confidence,
        recency_component=recency,
        tier_multiplier=tier_multiplier,
        tag_boost=tag_boost,
        passes_threshold=passes_threshold,
    )


def score_golden_standard(
    semantic_similarity: float,
    confidence: float,
    config: VariantConfig,
) -> tuple[float, bool]:
    """
    Score a golden standard for inclusion decision.

    Implements Decision d4: Golden standards must pass minimum semantic
    relevance threshold (0.25 default). Confidence=100 provides multiplier,
    not automatic inclusion.

    Args:
        semantic_similarity: Semantic similarity to query (0-1)
        confidence: Confidence score (0-100)
        config: Variant configuration

    Returns:
        Tuple of (score, passes_threshold)
    """
    # Check minimum semantic similarity threshold
    if semantic_similarity < config.golden_standard_min_similarity:
        return 0.0, False

    # Calculate score with confidence multiplier
    # Confidence=100 gives 1.5x multiplier
    confidence_multiplier = 1.0 + (confidence / 100.0) * 0.5

    score = semantic_similarity * confidence_multiplier

    passes = score >= config.min_relevance_threshold

    return score, passes


def rank_memories(
    scored_memories: list[tuple[Any, MemoryScore]],
    include_below_threshold: bool = False,
) -> list[tuple[Any, MemoryScore]]:
    """
    Rank memories by final score, optionally filtering by threshold.

    Args:
        scored_memories: List of (memory, score) tuples
        include_below_threshold: Whether to include items below threshold

    Returns:
        Sorted list of (memory, score) tuples, highest score first
    """
    if not include_below_threshold:
        scored_memories = [
            (m, s) for m, s in scored_memories if s.passes_threshold
        ]

    return sorted(
        scored_memories,
        key=lambda x: x[1].final_score,
        reverse=True,
    )
