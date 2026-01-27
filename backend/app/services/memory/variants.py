"""
A/B variant system for memory context injection optimization.

Provides deterministic variant assignment and configuration for different
injection strategies to enable A/B testing of memory relevance tuning.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MemoryVariant(str, Enum):
    """Memory injection variant for A/B testing."""

    BASELINE = "BASELINE"  # Current production behavior
    ENHANCED = "ENHANCED"  # Multi-factor scoring with higher weights
    MINIMAL = "MINIMAL"  # Higher thresholds, fewer items
    AGGRESSIVE = "AGGRESSIVE"  # Lower thresholds, more items


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


# Variant configurations
# BASELINE: Current behavior - standard weights, moderate thresholds
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
)

# ENHANCED: Higher semantic weight, stricter quality
ENHANCED_CONFIG = VariantConfig(
    variant=MemoryVariant.ENHANCED,
    scoring_weights=ScoringWeights(
        semantic=0.5,  # More weight on semantic similarity
        usage=0.25,
        confidence=0.15,
        recency=0.1,
    ),
    tier_multipliers=TierMultipliers(
        mandate=2.5,  # Higher mandate boost
        guardrail=1.8,
        reference=1.0,
    ),
    recency_config=RecencyConfig(
        mandate_half_life_days=45,
        reference_half_life_days=14,
    ),
    min_relevance_threshold=0.40,  # Higher threshold
    golden_standard_min_similarity=0.30,
)

# MINIMAL: Very strict filtering, fewer items injected
MINIMAL_CONFIG = VariantConfig(
    variant=MemoryVariant.MINIMAL,
    scoring_weights=ScoringWeights(
        semantic=0.6,  # Very high semantic weight
        usage=0.2,
        confidence=0.15,
        recency=0.05,
    ),
    tier_multipliers=TierMultipliers(
        mandate=3.0,
        guardrail=2.0,
        reference=1.0,
    ),
    recency_config=RecencyConfig(
        mandate_half_life_days=60,
        reference_half_life_days=21,
    ),
    min_relevance_threshold=0.50,  # Very high threshold
    golden_standard_min_similarity=0.35,
)

# AGGRESSIVE: Lower thresholds, more items injected
AGGRESSIVE_CONFIG = VariantConfig(
    variant=MemoryVariant.AGGRESSIVE,
    scoring_weights=ScoringWeights(
        semantic=0.35,  # Lower semantic weight
        usage=0.35,  # Higher usage weight
        confidence=0.20,
        recency=0.10,
    ),
    tier_multipliers=TierMultipliers(
        mandate=1.5,  # Lower mandate boost
        guardrail=1.3,
        reference=1.0,
    ),
    recency_config=RecencyConfig(
        mandate_half_life_days=20,
        reference_half_life_days=5,
    ),
    min_relevance_threshold=0.25,  # Lower threshold
    golden_standard_min_similarity=0.20,
)

# Mapping of variants to configs
VARIANT_CONFIGS: dict[MemoryVariant, VariantConfig] = {
    MemoryVariant.BASELINE: BASELINE_CONFIG,
    MemoryVariant.ENHANCED: ENHANCED_CONFIG,
    MemoryVariant.MINIMAL: MINIMAL_CONFIG,
    MemoryVariant.AGGRESSIVE: AGGRESSIVE_CONFIG,
}


def get_variant_config(variant: MemoryVariant | str) -> VariantConfig:
    """
    Get configuration for a variant.

    Args:
        variant: MemoryVariant enum or string name

    Returns:
        VariantConfig for the variant

    Raises:
        ValueError: If variant is unknown
    """
    if isinstance(variant, str):
        try:
            variant = MemoryVariant(variant)
        except ValueError:
            logger.warning("Unknown variant '%s', falling back to BASELINE", variant)
            variant = MemoryVariant.BASELINE

    return VARIANT_CONFIGS[variant]


# Bucket distribution for variant assignment
# Format: (cumulative_percentage, variant)
# 50% BASELINE, 30% ENHANCED, 10% MINIMAL, 10% AGGRESSIVE
VARIANT_BUCKETS: list[tuple[int, MemoryVariant]] = [
    (50, MemoryVariant.BASELINE),
    (80, MemoryVariant.ENHANCED),
    (90, MemoryVariant.MINIMAL),
    (100, MemoryVariant.AGGRESSIVE),
]


def assign_variant(
    external_id: str | None = None,
    project_id: str | None = None,
    variant_override: MemoryVariant | str | None = None,
) -> MemoryVariant:
    """
    Deterministically assign a variant based on hash of identifiers.

    Uses hash of external_id + project_id for consistent assignment.
    Same inputs always produce same variant (reproducibility).

    Args:
        external_id: External identifier (e.g., task ID)
        project_id: Project identifier
        variant_override: Optional override for testing (bypasses hash assignment)

    Returns:
        Assigned MemoryVariant

    Examples:
        >>> assign_variant(external_id="task-123", project_id="summitflow")
        MemoryVariant.BASELINE  # deterministic based on hash

        >>> assign_variant(variant_override="ENHANCED")
        MemoryVariant.ENHANCED  # override for testing
    """
    # Handle override
    if variant_override is not None:
        if isinstance(variant_override, str):
            try:
                return MemoryVariant(variant_override)
            except ValueError:
                logger.warning(
                    "Invalid variant override '%s', falling back to BASELINE",
                    variant_override,
                )
                return MemoryVariant.BASELINE
        return variant_override

    # Build hash input from identifiers
    # Use empty strings for None values to ensure consistent hashing
    hash_input = f"{external_id or ''}:{project_id or ''}"

    # If no identifiers provided, default to BASELINE
    if hash_input == ":":
        return MemoryVariant.BASELINE

    # Compute hash and map to 0-99 bucket
    hash_bytes = hashlib.md5(hash_input.encode(), usedforsecurity=False).digest()
    bucket = hash_bytes[0] % 100  # Use first byte mod 100

    # Find variant based on bucket
    for cumulative, variant in VARIANT_BUCKETS:
        if bucket < cumulative:
            logger.debug(
                "Assigned variant %s for hash_input=%s (bucket=%d)",
                variant.value,
                hash_input,
                bucket,
            )
            return variant

    # Fallback (should never reach due to 100% coverage)
    return MemoryVariant.BASELINE
