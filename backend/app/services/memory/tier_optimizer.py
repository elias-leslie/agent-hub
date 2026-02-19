"""
Tier Optimizer for autonomous memory tier management.

Implements ACE-aligned optimization (Decision d5 thresholds):
- Demote: utility_score < 0.15, loaded >= 200, age >= 7 days
- Demote zombie: ghost_ratio > 10, neutral avg rating
- Promote: utility_score > 0.70, referenced >= 20, age >= 7 days
- Grace period: 48 hours (no demotion for new episodes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .tier_operations import (
    demote_episode,
    get_next_tier_down,
    get_next_tier_up,
    log_tier_change,
    promote_episode,
)
from .tier_queries import calculate_ghost_ratio, find_demotion_candidates, find_promotion_candidates

logger = logging.getLogger(__name__)

# Optimization thresholds
DEMOTION_THRESHOLD = 0.15
PROMOTION_THRESHOLD = 0.70
MIN_LOADS_FOR_DEMOTION = 200  # Raised from 50 - need more signal before demoting
MIN_REFS_FOR_PROMOTION = 20
MIN_AGE_DAYS = 7
GRACE_PERIOD_HOURS = 48
GHOST_RATIO_THRESHOLD = 10

# ACE-aligned thresholds for agent citation ratings
HARMFUL_COUNT_THRESHOLD = 3  # Demote after 3+ harmful ratings
HELPFUL_COUNT_THRESHOLD = 5  # Promote after 5+ helpful ratings


@dataclass
class TierCandidate:
    """Candidate for tier optimization."""

    uuid: str
    name: str
    current_tier: str
    loaded_count: int
    referenced_count: int
    utility_score: float
    ghost_ratio: float
    age_hours: float
    reason: str


async def _apply_tier_changes(
    candidates: list[dict[str, Any]],
    get_next_tier: Any,
    apply_change: Any,
    action: str,
    log_action: str,
    count_key: str,
    results: dict[str, Any],
) -> None:
    """Apply tier changes for a list of candidates, updating results in place."""
    for candidate in candidates:
        new_tier = get_next_tier(candidate["current_tier"])
        if new_tier:
            success = await apply_change(candidate["uuid"], new_tier, candidate["reason"])
            if success:
                await log_tier_change(
                    candidate["uuid"],
                    candidate["current_tier"],
                    new_tier,
                    candidate["reason"],
                    log_action,
                )
                results[count_key] += 1
                results["details"].append(
                    {
                        "uuid": candidate["uuid"][:8],
                        "action": action,
                        "from": candidate["current_tier"],
                        "to": new_tier,
                        "reason": candidate["reason"],
                    }
                )
            else:
                results["errors"] += 1


async def optimize_tiers() -> dict[str, Any]:
    """Run the tier optimization cycle (demotions then promotions).

    Finds candidates, applies tier changes, logs all changes to the audit table.
    Returns a summary dict with keys: demotions, promotions, errors, details.
    """
    results: dict[str, Any] = {"demotions": 0, "promotions": 0, "errors": 0, "details": []}

    demotion_candidates = await find_demotion_candidates(
        min_loads=MIN_LOADS_FOR_DEMOTION,
        grace_period_hours=GRACE_PERIOD_HOURS,
        min_age_days=MIN_AGE_DAYS,
        harmful_threshold=HARMFUL_COUNT_THRESHOLD,
        demotion_threshold=DEMOTION_THRESHOLD,
        ghost_ratio_threshold=GHOST_RATIO_THRESHOLD,
    )
    await _apply_tier_changes(
        demotion_candidates, get_next_tier_down, demote_episode, "demote", "demotion", "demotions", results
    )

    promotion_candidates = await find_promotion_candidates(
        min_refs=MIN_REFS_FOR_PROMOTION,
        min_age_days=MIN_AGE_DAYS,
        helpful_threshold=HELPFUL_COUNT_THRESHOLD,
        promotion_threshold=PROMOTION_THRESHOLD,
    )
    await _apply_tier_changes(
        promotion_candidates, get_next_tier_up, promote_episode, "promote", "promotion", "promotions", results
    )

    logger.info(
        "Tier optimization complete: %d demotions, %d promotions, %d errors",
        results["demotions"],
        results["promotions"],
        results["errors"],
    )

    return results


# Re-export for backward compatibility
__all__ = [
    # Thresholds
    "DEMOTION_THRESHOLD",
    "GHOST_RATIO_THRESHOLD",
    "GRACE_PERIOD_HOURS",
    "HARMFUL_COUNT_THRESHOLD",
    "HELPFUL_COUNT_THRESHOLD",
    "MIN_AGE_DAYS",
    "MIN_LOADS_FOR_DEMOTION",
    "MIN_REFS_FOR_PROMOTION",
    "PROMOTION_THRESHOLD",
    # Classes and functions
    "TierCandidate",
    "calculate_ghost_ratio",
    "demote_episode",
    "find_demotion_candidates",
    "find_promotion_candidates",
    "get_next_tier_down",
    "get_next_tier_up",
    "log_tier_change",
    "optimize_tiers",
    "promote_episode",
]
