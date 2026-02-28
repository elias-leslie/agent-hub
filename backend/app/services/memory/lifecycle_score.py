"""Continuous lifecycle scoring for memory tier management.

Replaces the binary utility_score with a multi-factor continuous score:
  score = (0.40*citation_rate + 0.25*feedback + 0.20*decay + 0.15*grace) * stickiness

Each tier has its own parameters (expected cite rate, decay half-life, etc).
Pinned memories are scored for observability but never acted on.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_REVERSE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TierLifecycleConfig:
    """Per-tier parameters for lifecycle scoring."""

    expected_cite_rate: float  # citations / loads expected
    decay_half_life_days: int  # temporal decay half-life
    grace_period_days: int  # new memory grace period
    stickiness: float  # multiplier (mandates stick harder)
    demotion_threshold: float  # score below this => demotion candidate
    promotion_threshold: float  # score above this => promotion candidate


TIER_CONFIGS: dict[str, TierLifecycleConfig] = {
    "mandate": TierLifecycleConfig(
        expected_cite_rate=0.20,
        decay_half_life_days=90,
        grace_period_days=14,
        stickiness=1.3,
        demotion_threshold=0.25,
        promotion_threshold=0.80,
    ),
    "guardrail": TierLifecycleConfig(
        expected_cite_rate=0.15,
        decay_half_life_days=60,
        grace_period_days=10,
        stickiness=1.15,
        demotion_threshold=0.30,
        promotion_threshold=0.70,
    ),
    "reference": TierLifecycleConfig(
        expected_cite_rate=0.10,
        decay_half_life_days=30,
        grace_period_days=7,
        stickiness=1.0,
        demotion_threshold=0.35,
        promotion_threshold=0.65,
    ),
    "archive": TierLifecycleConfig(
        expected_cite_rate=0.05,
        decay_half_life_days=14,
        grace_period_days=3,
        stickiness=0.85,
        demotion_threshold=0.20,
        promotion_threshold=0.55,
    ),
}


def compute_lifecycle_score(
    *,
    tier: str,
    loaded_count: int,
    referenced_count: int,
    helpful_count: int,
    harmful_count: int,
    created_at: datetime,
    last_accessed_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """Compute a continuous lifecycle score for a memory.

    Returns a float in [0, ~1.3] (stickiness can push above 1.0).

    Components (weighted):
      citation_rate  (0.40) — actual cite rate vs expected
      feedback_signal(0.25) — helpful minus harmful, normalized
      temporal_decay (0.20) — exponential decay from last access
      age_grace      (0.15) — grace period boost for new memories
    """
    if now is None:
        now = datetime.now(UTC)

    cfg = TIER_CONFIGS.get(tier, TIER_CONFIGS["reference"])

    # --- Citation rate (0.40) ---
    if loaded_count > 0:
        actual_rate = referenced_count / loaded_count
        citation_rate = min(actual_rate / cfg.expected_cite_rate, 1.0)
    else:
        # Not yet loaded — full credit during evaluation
        citation_rate = 1.0

    # --- Feedback signal (0.25) ---
    total_feedback = helpful_count + harmful_count
    feedback_signal = helpful_count / total_feedback if total_feedback > 0 else 0.5

    # --- Temporal decay (0.20) ---
    last_touch = last_accessed_at or created_at
    days_since = max((now - last_touch).total_seconds() / 86400, 0)
    # Exponential decay: 1.0 at day 0, 0.5 at half_life
    temporal_decay = math.pow(0.5, days_since / cfg.decay_half_life_days)

    # --- Age grace (0.15) ---
    age_days = max((now - created_at).total_seconds() / 86400, 0)
    if age_days <= cfg.grace_period_days:
        age_grace = 1.0
    else:
        # Decays linearly from 1.0 to 0.0 over 2x grace period after grace ends
        overage = age_days - cfg.grace_period_days
        age_grace = max(1.0 - overage / (cfg.grace_period_days * 2), 0.0)

    # --- Combine ---
    raw = (
        0.40 * citation_rate
        + 0.25 * feedback_signal
        + 0.20 * temporal_decay
        + 0.15 * age_grace
    )
    return round(raw * cfg.stickiness, 4)


async def batch_update_lifecycle_scores() -> dict[str, Any]:
    """Compute and persist lifecycle_score for all active memories.

    Returns summary: {updated, by_tier: {tier: {count, avg_score}}}.
    """
    now = datetime.now(UTC)
    updated = 0
    by_tier: dict[str, dict[str, Any]] = {}

    async with async_session() as session:
        stmt = select(Memory).where(Memory.status.in_(["active", "archived"]))
        result = await session.execute(stmt)
        memories = list(result.scalars().all())

        for mem in memories:
            tier_name = TIER_REVERSE.get(mem.tier, "reference")
            score = compute_lifecycle_score(
                tier=tier_name,
                loaded_count=mem.loaded_count,
                referenced_count=mem.referenced_count,
                helpful_count=mem.helpful_count,
                harmful_count=mem.harmful_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                now=now,
            )

            await session.execute(
                update(Memory)
                .where(Memory.id == mem.id)
                .values(lifecycle_score=score, lifecycle_score_updated_at=now)
            )
            updated += 1

            # Accumulate tier stats
            if tier_name not in by_tier:
                by_tier[tier_name] = {"count": 0, "total_score": 0.0}
            by_tier[tier_name]["count"] += 1
            by_tier[tier_name]["total_score"] += score

        await session.commit()

    # Compute averages
    tier_stats = {}
    for tier_name, data in by_tier.items():
        tier_stats[tier_name] = {
            "count": data["count"],
            "avg_score": round(data["total_score"] / data["count"], 4) if data["count"] else 0,
        }

    logger.info("Lifecycle scores updated for %d memories: %s", updated, tier_stats)
    return {"updated": updated, "by_tier": tier_stats}
