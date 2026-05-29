"""Tier Optimizer: autonomous memory tier management via lifecycle scores.

Steps: batch-update scores, demote low-scoring memories,
promote high-scoring ones, self-heal archived memories with rising citations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TypedDict

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

MIN_LOADS_FOR_DEMOTION = 200
MIN_REFS_FOR_PROMOTION = 20
MIN_AGE_DAYS = 7
GRACE_PERIOD_HOURS = 48
GHOST_RATIO_THRESHOLD = 10
HARMFUL_COUNT_THRESHOLD = 3
HELPFUL_COUNT_THRESHOLD = 5
# Score thresholds are now per-tier and sourced from
# lifecycle_score.TIER_CONFIGS inside the candidate-selection logic.

_TierFn = Callable[[str], str | None]
_ApplyFn = Callable[[str, str, str], Coroutine[None, None, bool]]


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


class _OptResult(TypedDict):
    demotions: int
    promotions: int
    self_heals: int
    errors: int
    details: list[dict[str, object]]
    lifecycle_update: dict[str, object]


async def _apply_tier_changes(
    candidates: list[dict[str, object]],
    get_next_tier: _TierFn,
    apply_change: _ApplyFn,
    action: str,
    log_action: str,
    count_key: str,
    results: _OptResult,
) -> None:
    """Apply tier changes for a list of candidates, updating results in place."""
    for c in candidates:
        tier = str(c["current_tier"])
        new_tier = get_next_tier(tier)
        if not new_tier:
            continue
        uuid, reason = str(c["uuid"]), str(c["reason"])
        if not await apply_change(uuid, new_tier, reason):
            results["errors"] += 1
            continue
        lc = c.get("lifecycle_score")
        await log_tier_change(uuid, tier, new_tier, reason, log_action, lifecycle_score_before=lc)
        results[count_key] += 1  # type: ignore[literal-required]
        results["details"].append({"uuid": uuid[:8], "action": action, "from": tier,
                                   "to": new_tier, "reason": reason, "lifecycle_score": lc})


async def optimize_tiers() -> _OptResult:
    """Run the tier optimization cycle.

    Returns a summary dict with keys: demotions, promotions, self_heals,
    lifecycle_update, errors, details.
    """
    results: _OptResult = {
        "demotions": 0, "promotions": 0, "self_heals": 0,
        "errors": 0, "details": [], "lifecycle_update": {},
    }

    try:
        lc = await batch_update_lifecycle_scores()
        results["lifecycle_update"] = lc
        logger.info("Lifecycle scores updated: %d memories", lc.get("updated", 0))
    except Exception as e:
        logger.error("Failed to update lifecycle scores: %s", e)
        results["errors"] += 1

    await _apply_tier_changes(
        await find_demotion_candidates(
            min_loads=MIN_LOADS_FOR_DEMOTION, grace_period_hours=GRACE_PERIOD_HOURS,
            min_age_days=MIN_AGE_DAYS, harmful_threshold=HARMFUL_COUNT_THRESHOLD,
            ghost_ratio_threshold=GHOST_RATIO_THRESHOLD,
        ),
        get_next_tier_down, demote_episode, "demote", "demotion", "demotions", results,
    )

    await _apply_tier_changes(
        await find_promotion_candidates(
            min_refs=MIN_REFS_FOR_PROMOTION, min_age_days=MIN_AGE_DAYS,
            helpful_threshold=HELPFUL_COUNT_THRESHOLD,
        ),
        get_next_tier_up, promote_episode, "promote", "promotion", "promotions", results,
    )

    try:
        from .self_heal import find_and_apply_self_heals
        heal = await find_and_apply_self_heals()
        results["self_heals"] = heal.get("healed", 0)
        if heal.get("details"):
            results["details"].extend(heal["details"])
    except Exception as e:
        logger.error("Self-healing pass failed: %s", e)
        results["errors"] += 1
    logger.info(
        "Tier optimization complete: %d demotions, %d promotions, %d self-heals, %d errors",
        results["demotions"], results["promotions"], results["self_heals"], results["errors"],
    )
    return results


__all__ = [
    "GHOST_RATIO_THRESHOLD", "GRACE_PERIOD_HOURS", "HARMFUL_COUNT_THRESHOLD",
    "HELPFUL_COUNT_THRESHOLD", "MIN_AGE_DAYS", "MIN_LOADS_FOR_DEMOTION", "MIN_REFS_FOR_PROMOTION",
    "TierCandidate", "calculate_ghost_ratio", "demote_episode",
    "find_demotion_candidates", "find_promotion_candidates", "get_next_tier_down",
    "get_next_tier_up", "log_tier_change", "optimize_tiers", "promote_episode",
]
