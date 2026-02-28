"""Tier Optimizer for autonomous memory tier management.

Uses continuous lifecycle scores for tier decisions:
1. Batch-update lifecycle_score for all active memories
2. Find demotion candidates (score below tier-specific threshold)
3. Find promotion candidates (score above tier-specific threshold)
4. Run self-healing pass for archived memories with rising citations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .lifecycle_score import batch_update_lifecycle_scores
from .tier_operations import (
    demote_episode,
    get_next_tier_down,
    get_next_tier_up,
    log_tier_change,
    promote_episode,
)
from .tier_queries import (
    calculate_ghost_ratio,
    find_demotion_candidates,
    find_promotion_candidates,
)

logger = logging.getLogger(__name__)

# Minimum signal thresholds (safety guards — even with lifecycle scores,
# we don't act on memories with too little data)
MIN_LOADS_FOR_DEMOTION = 200
MIN_REFS_FOR_PROMOTION = 20
MIN_AGE_DAYS = 7
GRACE_PERIOD_HOURS = 48
GHOST_RATIO_THRESHOLD = 10
HARMFUL_COUNT_THRESHOLD = 3
HELPFUL_COUNT_THRESHOLD = 5

# Legacy thresholds (used by tier_queries for candidate filtering)
DEMOTION_THRESHOLD = 0.15
PROMOTION_THRESHOLD = 0.70


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
        if not new_tier:
            continue
        success = await apply_change(candidate["uuid"], new_tier, candidate["reason"])
        if success:
            await log_tier_change(
                candidate["uuid"],
                candidate["current_tier"],
                new_tier,
                candidate["reason"],
                log_action,
                lifecycle_score_before=candidate.get("lifecycle_score"),
            )
            results[count_key] += 1
            results["details"].append(
                {
                    "uuid": candidate["uuid"][:8],
                    "action": action,
                    "from": candidate["current_tier"],
                    "to": new_tier,
                    "reason": candidate["reason"],
                    "lifecycle_score": candidate.get("lifecycle_score"),
                }
            )
        else:
            results["errors"] += 1


async def optimize_tiers() -> dict[str, Any]:
    """Run the tier optimization cycle.

    Steps:
    1. Batch-update lifecycle_score for all active memories
    2. Find and apply demotions (lifecycle_score < tier threshold)
    3. Find and apply promotions (lifecycle_score > tier threshold)
    4. Run self-healing for archived memories with rising citations

    Returns a summary dict with keys: demotions, promotions, self_heals,
    lifecycle_update, errors, details.
    """
    results: dict[str, Any] = {
        "demotions": 0,
        "promotions": 0,
        "self_heals": 0,
        "errors": 0,
        "details": [],
        "lifecycle_update": {},
    }

    # Step 1: Update lifecycle scores for all memories
    try:
        results["lifecycle_update"] = await batch_update_lifecycle_scores()
        logger.info(
            "Lifecycle scores updated: %d memories",
            results["lifecycle_update"].get("updated", 0),
        )
    except Exception as e:
        logger.error("Failed to update lifecycle scores: %s", e)
        results["errors"] += 1

    # Step 2: Find and apply demotions
    demotion_candidates = await find_demotion_candidates(
        min_loads=MIN_LOADS_FOR_DEMOTION,
        grace_period_hours=GRACE_PERIOD_HOURS,
        min_age_days=MIN_AGE_DAYS,
        harmful_threshold=HARMFUL_COUNT_THRESHOLD,
        demotion_threshold=DEMOTION_THRESHOLD,
        ghost_ratio_threshold=GHOST_RATIO_THRESHOLD,
    )
    await _apply_tier_changes(
        demotion_candidates, get_next_tier_down, demote_episode,
        "demote", "demotion", "demotions", results,
    )

    # Step 3: Find and apply promotions
    promotion_candidates = await find_promotion_candidates(
        min_refs=MIN_REFS_FOR_PROMOTION,
        min_age_days=MIN_AGE_DAYS,
        helpful_threshold=HELPFUL_COUNT_THRESHOLD,
        promotion_threshold=PROMOTION_THRESHOLD,
    )
    await _apply_tier_changes(
        promotion_candidates, get_next_tier_up, promote_episode,
        "promote", "promotion", "promotions", results,
    )

    # Step 4: Self-healing pass
    try:
        from .self_heal import find_and_apply_self_heals

        heal_results = await find_and_apply_self_heals()
        results["self_heals"] = heal_results.get("healed", 0)
        if heal_results.get("details"):
            results["details"].extend(heal_results["details"])
    except Exception as e:
        logger.error("Self-healing pass failed: %s", e)
        results["errors"] += 1

    logger.info(
        "Tier optimization complete: %d demotions, %d promotions, %d self-heals, %d errors",
        results["demotions"],
        results["promotions"],
        results["self_heals"],
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
    "log_tier_change",
    "optimize_tiers",
    "promote_episode",
]
