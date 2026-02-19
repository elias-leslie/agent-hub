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
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .scoring_helpers import (
    _get_recency_half_life,
    _get_tier_multiplier,
    calculate_recency_decay,
    calculate_usage_effectiveness,
)
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

    # Token count for utility-per-token scoring
    token_count: int = 0


@dataclass
class MemoryScore:
    """Result of scoring a memory item."""

    final_score: float  # Combined weighted score (0.0 - 1.0+)
    semantic_component: float
    usage_component: float
    confidence_component: float
    recency_component: float
    tier_multiplier: float
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
            "passes": self.passes_threshold,
        }


def _calculate_components(
    input_data: MemoryScoreInput,
    config: VariantConfig,
    now: datetime | None,
) -> tuple[float, float, float, float]:
    """
    Compute the four scoring components: semantic, usage, confidence, recency.

    Returns:
        Tuple of (semantic, usage, confidence, recency) floats, each 0.0-1.0.
    """
    semantic = max(0.0, min(1.0, input_data.semantic_similarity))
    usage = calculate_usage_effectiveness(input_data.loaded_count, input_data.referenced_count)
    confidence = max(0.0, min(1.0, input_data.confidence / 100.0))

    half_life = _get_recency_half_life(input_data.tier, config.recency_config)
    recency = calculate_recency_decay(input_data.created_at, input_data.last_used_at, half_life, now)

    return semantic, usage, confidence, recency


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

    semantic, usage, confidence, recency = _calculate_components(input_data, config, now)

    base_score = (
        semantic * weights.semantic
        + usage * weights.usage
        + confidence * weights.confidence
        + recency * weights.recency
    )

    tier_multiplier = _get_tier_multiplier(input_data.tier, config.tier_multipliers)
    final_score = base_score * tier_multiplier
    passes_threshold = final_score >= config.min_relevance_threshold

    return MemoryScore(
        final_score=final_score,
        semantic_component=semantic,
        usage_component=usage,
        confidence_component=confidence,
        recency_component=recency,
        tier_multiplier=tier_multiplier,
        passes_threshold=passes_threshold,
    )
