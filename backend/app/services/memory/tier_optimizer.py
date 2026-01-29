"""
Tier Optimizer for autonomous memory tier management.

Implements ACE-aligned optimization:
- Promotes high-utility episodes to higher tiers
- Demotes low-utility episodes to lower tiers
- Detects zombies (high load, zero reference) for cleanup
- Respects grace period for new episodes
- Logs all tier changes for audit trail

Thresholds (from Decision d5):
- Demote: utility_score < 0.15, loaded >= 200, age >= 7 days
- Demote zombie: ghost_ratio > 10, neutral avg rating
- Promote: utility_score > 0.70, referenced >= 20, age >= 7 days
- Grace period: 48 hours (no demotion for new episodes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .tier_corrections import handle_harmful_episode as _handle_harmful_episode
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


async def handle_harmful_episode(
    episode_uuid: str,
    correction_content: str | None = None,
) -> bool:
    """
    Handle an episode that has harmful rating majority.

    Wrapper around tier_corrections.handle_harmful_episode that provides log_tier_change_fn.

    Args:
        episode_uuid: UUID of the harmful episode
        correction_content: Optional corrected content to replace harmful one

    Returns:
        True if handled successfully, False otherwise
    """
    return await _handle_harmful_episode(episode_uuid, correction_content, log_tier_change)


async def optimize_tiers() -> dict[str, Any]:
    """
    Run the tier optimization cycle.

    1. Find demotion candidates (low utility, zombies)
    2. Find promotion candidates (high utility)
    3. Apply tier changes
    4. Log all changes to audit table

    Returns:
        Summary of optimization results.
    """
    results: dict[str, Any] = {
        "demotions": 0,
        "promotions": 0,
        "errors": 0,
        "details": [],
    }

    # Process demotions
    demotion_candidates = await find_demotion_candidates(
        min_loads=MIN_LOADS_FOR_DEMOTION,
        grace_period_hours=GRACE_PERIOD_HOURS,
        min_age_days=MIN_AGE_DAYS,
        harmful_threshold=HARMFUL_COUNT_THRESHOLD,
        demotion_threshold=DEMOTION_THRESHOLD,
        ghost_ratio_threshold=GHOST_RATIO_THRESHOLD,
    )

    for candidate in demotion_candidates:
        new_tier = get_next_tier_down(candidate["current_tier"])
        if new_tier:
            success = await demote_episode(candidate["uuid"], new_tier, candidate["reason"])
            if success:
                await log_tier_change(
                    candidate["uuid"],
                    candidate["current_tier"],
                    new_tier,
                    candidate["reason"],
                    "demotion",
                )
                results["demotions"] += 1
                results["details"].append(
                    {
                        "uuid": candidate["uuid"][:8],
                        "action": "demote",
                        "from": candidate["current_tier"],
                        "to": new_tier,
                        "reason": candidate["reason"],
                    }
                )
            else:
                results["errors"] += 1

    # Process promotions
    promotion_candidates = await find_promotion_candidates(
        min_refs=MIN_REFS_FOR_PROMOTION,
        min_age_days=MIN_AGE_DAYS,
        helpful_threshold=HELPFUL_COUNT_THRESHOLD,
        promotion_threshold=PROMOTION_THRESHOLD,
    )

    for candidate in promotion_candidates:
        new_tier = get_next_tier_up(candidate["current_tier"])
        if new_tier:
            success = await promote_episode(candidate["uuid"], new_tier, candidate["reason"])
            if success:
                await log_tier_change(
                    candidate["uuid"],
                    candidate["current_tier"],
                    new_tier,
                    candidate["reason"],
                    "promotion",
                )
                results["promotions"] += 1
                results["details"].append(
                    {
                        "uuid": candidate["uuid"][:8],
                        "action": "promote",
                        "from": candidate["current_tier"],
                        "to": new_tier,
                        "reason": candidate["reason"],
                    }
                )
            else:
                results["errors"] += 1

    logger.info(
        "Tier optimization complete: %d demotions, %d promotions, %d errors",
        results["demotions"],
        results["promotions"],
        results["errors"],
    )

    return results


# Re-export for backward compatibility
__all__ = [
    "DEMOTION_THRESHOLD",
    "GHOST_RATIO_THRESHOLD",
    "GRACE_PERIOD_HOURS",
    "HARMFUL_COUNT_THRESHOLD",
    "HELPFUL_COUNT_THRESHOLD",
    "MIN_AGE_DAYS",
    "MIN_LOADS_FOR_DEMOTION",
    "MIN_REFS_FOR_PROMOTION",
    "PROMOTION_THRESHOLD",
    "TierCandidate",
    "calculate_ghost_ratio",
    "demote_episode",
    "find_demotion_candidates",
    "find_promotion_candidates",
    "get_next_tier_down",
    "get_next_tier_up",
    "handle_harmful_episode",
    "log_tier_change",
    "optimize_tiers",
    "promote_episode",
]
