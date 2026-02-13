"""Backward compatibility shim for tier_classifier - DEPRECATED.

Use app.services.model_selector instead.
This module maintains backward compatibility for existing code.
"""

from __future__ import annotations

import warnings

from app.services.model_selector import (
    ComplexityTier as Tier,
)
from app.services.model_selector import (
    QualityPreference,
)
from app.services.model_selector import (
    classify_complexity as _classify_complexity,
)
from app.services.model_selector import (
    select_model as _select_model,
)

# Re-export for backward compatibility
__all__ = ["Tier", "classify_and_select_model", "classify_request", "get_model_for_tier"]


def classify_request(prompt: str, context: str | None = None) -> Tier:
    """Classify a request into a complexity tier.

    DEPRECATED: Use model_selector.classify_complexity instead.
    """
    warnings.warn(
        "tier_classifier.classify_request is deprecated. Use model_selector.classify_complexity",
        DeprecationWarning,
        stacklevel=2,
    )
    return _classify_complexity(prompt, context)


def get_model_for_tier(tier: Tier, provider: str = "claude") -> str:
    """Get the appropriate model for a tier and provider.

    DEPRECATED: Use model_selector.select_model instead.
    """
    warnings.warn(
        "tier_classifier.get_model_for_tier is deprecated. Use model_selector.select_model",
        DeprecationWarning,
        stacklevel=2,
    )
    # Map tiers to preferences matching old hardcoded behavior
    tier_to_pref = {
        Tier.TIER_4: QualityPreference.ADVANCED,
        Tier.TIER_3: QualityPreference.ADVANCED,
        Tier.TIER_2: QualityPreference.STANDARD,
        Tier.TIER_1: QualityPreference.ECONOMY,
    }
    model_entry = _select_model(
        complexity=tier,
        preference=tier_to_pref.get(tier, QualityPreference.STANDARD),
        provider=provider,
    )
    return model_entry.id


def classify_and_select_model(
    prompt: str,
    context: str | None = None,
    provider: str = "claude",
    explicit_model: str | None = None,
) -> tuple[Tier, str]:
    """Classify request and select appropriate model.

    DEPRECATED: Use model_selector.select_model_for_request instead.
    """
    warnings.warn(
        "tier_classifier.classify_and_select_model is deprecated. Use model_selector",
        DeprecationWarning,
        stacklevel=2,
    )

    tier = classify_request(prompt, context)

    if explicit_model:
        return tier, explicit_model

    return tier, get_model_for_tier(tier, provider)
