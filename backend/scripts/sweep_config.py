"""Configuration generation for parameter sweep."""

import itertools
from dataclasses import dataclass, field
from typing import Any

# Parameter grid for sweep
PARAMETER_GRID = {
    "semantic_weight": [0.3, 0.4, 0.5, 0.6],
    "usage_weight": [0.2, 0.25, 0.3, 0.35],
    "min_relevance_threshold": [0.25, 0.35, 0.45, 0.55],
    "golden_standard_min_similarity": [0.20, 0.25, 0.30, 0.35],
    "mandate_multiplier": [1.5, 2.0, 2.5, 3.0],
    "guardrail_multiplier": [1.3, 1.5, 1.8, 2.0],
    "mandate_half_life_days": [20, 30, 45, 60],
}


@dataclass
class ParameterConfig:
    """A single parameter configuration to evaluate."""

    semantic_weight: float
    usage_weight: float
    recency_weight: float = 0.1
    min_relevance_threshold: float = 0.35
    golden_standard_min_similarity: float = 0.25
    mandate_multiplier: float = 2.0
    guardrail_multiplier: float = 1.5
    mandate_half_life_days: int = 30
    confidence_weight: float = field(init=False)

    def __post_init__(self):
        """Calculate confidence weight to ensure sum = 1.0."""
        self.confidence_weight = round(
            1.0 - self.semantic_weight - self.usage_weight - self.recency_weight, 2
        )
        if self.confidence_weight < 0:
            raise ValueError(
                f"Invalid weight combination: semantic={self.semantic_weight}, "
                f"usage={self.usage_weight}, recency={self.recency_weight}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "semantic_weight": self.semantic_weight,
            "usage_weight": self.usage_weight,
            "confidence_weight": self.confidence_weight,
            "recency_weight": self.recency_weight,
            "min_relevance_threshold": self.min_relevance_threshold,
            "golden_standard_min_similarity": self.golden_standard_min_similarity,
            "mandate_multiplier": self.mandate_multiplier,
            "guardrail_multiplier": self.guardrail_multiplier,
            "mandate_half_life_days": self.mandate_half_life_days,
        }


def generate_configs() -> list[ParameterConfig]:
    """Generate all valid parameter configurations from the grid."""
    configs = []
    for (semantic, usage, threshold, golden_sim, mandate_mult, guardrail_mult, half_life) in itertools.product(
        PARAMETER_GRID["semantic_weight"],
        PARAMETER_GRID["usage_weight"],
        PARAMETER_GRID["min_relevance_threshold"],
        PARAMETER_GRID["golden_standard_min_similarity"],
        PARAMETER_GRID["mandate_multiplier"],
        PARAMETER_GRID["guardrail_multiplier"],
        PARAMETER_GRID["mandate_half_life_days"],
    ):
        if semantic + usage > 0.9:
            continue
        try:
            configs.append(
                ParameterConfig(
                    semantic_weight=semantic,
                    usage_weight=usage,
                    min_relevance_threshold=threshold,
                    golden_standard_min_similarity=golden_sim,
                    mandate_multiplier=mandate_mult,
                    guardrail_multiplier=guardrail_mult,
                    mandate_half_life_days=half_life,
                )
            )
        except ValueError:
            continue
    return configs
