"""Memory injection scoring config.

Retrieval uses one config, BASELINE. The old A/B split (50% BASELINE, 30% ENHANCED,
10% MINIMAL, 10% AGGRESSIVE by request hash) ran with no variant ever promoted, so it
is gone; variant fields that clients still send are accepted and ignored.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class MemoryVariant(StrEnum):
    """The memory injection config label recorded in metrics."""

    BASELINE = "BASELINE"


@dataclass
class ScoringWeights:
    """Weight distribution for multi-factor scoring."""

    semantic: float = 0.4  # Semantic similarity weight
    usage: float = 0.3  # Usage effectiveness weight
    confidence: float = 0.2  # Confidence score weight
    recency: float = 0.1  # Recency decay weight

    def __post_init__(self) -> None:
        """Validate weights sum to 1.0."""
        total = self.semantic + self.usage + self.confidence + self.recency
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")


@dataclass
class TierMultipliers:
    """Score multipliers for different memory tiers."""

    mandate: float = 2.0  # Mandates (golden standards)
    guardrail: float = 1.5  # Guardrails (anti-patterns)
    reference: float = 1.0  # Reference (patterns, workflows)


@dataclass
class RecencyConfig:
    """Recency decay configuration."""

    mandate_half_life_days: int = 30  # Half-life for mandate decay
    reference_half_life_days: int = 7  # Half-life for reference decay


@dataclass
class VariantConfig:
    """Configuration for a memory injection variant."""

    variant: MemoryVariant
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)
    tier_multipliers: TierMultipliers = field(default_factory=TierMultipliers)
    recency_config: RecencyConfig = field(default_factory=RecencyConfig)
    min_relevance_threshold: float = 0.35  # Minimum score for inclusion
    golden_standard_min_similarity: float = 0.25  # Min semantic similarity for golden standards
    max_reference_items: int = 6
    max_query_selected_references: int = 3


BASELINE_CONFIG = VariantConfig(
    variant=MemoryVariant.BASELINE,
    scoring_weights=ScoringWeights(
        semantic=0.4,
        usage=0.3,
        confidence=0.2,
        recency=0.1,
    ),
    tier_multipliers=TierMultipliers(
        mandate=2.0,
        guardrail=1.5,
        reference=1.0,
    ),
    recency_config=RecencyConfig(
        mandate_half_life_days=30,
        reference_half_life_days=7,
    ),
    min_relevance_threshold=0.35,
    golden_standard_min_similarity=0.25,
    max_reference_items=6,
    max_query_selected_references=3,
)


def get_variant_config() -> VariantConfig:
    """Return the memory injection scoring config."""
    return BASELINE_CONFIG
