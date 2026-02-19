"""
Helper functions for multi-factor memory scoring.

Contains recency decay, usage effectiveness, and tier-selection utilities
extracted from scoring.py to keep functions under 50 lines.
"""

import math
from datetime import UTC, datetime
from typing import Any


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


def _get_recency_half_life(tier: str, recency_config: Any) -> int:
    """Return the tier-appropriate recency half-life in days."""
    if tier == "mandate":
        return recency_config.mandate_half_life_days
    return recency_config.reference_half_life_days


def _get_tier_multiplier(tier: str, tiers: Any) -> float:
    """Return the multiplier for the given memory tier."""
    if tier == "mandate":
        return tiers.mandate
    if tier == "guardrail":
        return tiers.guardrail
    return tiers.reference
