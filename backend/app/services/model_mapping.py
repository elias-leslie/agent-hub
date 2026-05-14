"""Model mapping utilities for provider fallback."""

from __future__ import annotations

from app.constants import (
    GEMINI_FLASH,
    MODEL_CATALOG,
    MODEL_CATALOG_BY_ID,
)
from app.routing.registry import is_workload_provider


def get_fallback_model(model_id: str, target_provider: str) -> str | None:
    """Get fallback model in target provider based on score equivalence.

    Computes fallback using MODEL_CATALOG composite scores instead of hardcoded maps.

    Args:
        model_id: Original model identifier
        target_provider: Target provider name

    Returns:
        Mapped model identifier for target provider, or None if not found
    """
    if not is_workload_provider(target_provider) or model_id not in MODEL_CATALOG_BY_ID:
        return None
    source_score = MODEL_CATALOG_BY_ID[model_id].scores.composite
    candidates = [m for m in MODEL_CATALOG if m.provider == target_provider]
    if not candidates:
        return None
    candidates.sort(key=lambda m: abs(m.scores.composite - source_score))
    return candidates[0].id


def map_model_to_provider(original_model: str, target_provider: str) -> str:
    """Map a model from one provider to an equivalent in another.

    Uses score-based equivalence for intelligent fallback.

    Args:
        original_model: Original model identifier
        target_provider: Target provider name

    Returns:
        Mapped model identifier for target provider
    """
    # Try score-based equivalence
    equivalent = get_fallback_model(original_model, target_provider)
    if equivalent:
        return equivalent

    # Fallback to provider defaults
    if target_provider == "gemini":
        return GEMINI_FLASH
    else:
        # Try to find any model from target provider
        candidates = [m for m in MODEL_CATALOG if m.provider == target_provider]
        if candidates:
            return candidates[0].id
        return original_model
