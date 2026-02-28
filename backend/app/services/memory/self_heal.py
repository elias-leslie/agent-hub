"""Self-healing for archived memories that start getting cited again.

Detection criteria (either triggers promotion back to reference tier):
  - referenced_count delta >= 3 in the last 7 days
  - lifecycle_score exceeds archive promotion threshold (0.55)

Pinned memories are never in archive, so self-heal doesn't apply to them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select

from app.db import async_session
from app.models.memory_unified import Memory

from .lifecycle_score import TIER_CONFIGS
from .tier_operations import get_next_tier_up, log_tier_change, promote_episode

logger = logging.getLogger(__name__)

# Self-heal thresholds
MIN_REF_DELTA = 3  # minimum reference increase in window
REF_WINDOW_DAYS = 7  # window for measuring reference delta


async def find_and_apply_self_heals() -> dict[str, Any]:
    """Find archived memories with rising citations and promote them.

    An archived memory qualifies for self-healing if:
      1. lifecycle_score >= archive promotion threshold (0.55), OR
      2. It was recently accessed (last_accessed_at within 7 days) AND
         referenced_count suggests active use (>= MIN_REF_DELTA total refs)

    Returns dict with {healed, skipped, details}.
    """
    results: dict[str, Any] = {"healed": 0, "skipped": 0, "details": []}
    archive_cfg = TIER_CONFIGS["archive"]
    now = datetime.now(UTC)
    recent_cutoff = now - timedelta(days=REF_WINDOW_DAYS)

    async with async_session() as session:
        # Find archived, non-pinned memories with some signal
        stmt = select(Memory).where(
            and_(
                Memory.status == "active",
                Memory.tier == 4,  # archive
                Memory.pinned == False,  # noqa: E712
                Memory.superseded_by.is_(None),  # not consolidated
            )
        )
        result = await session.execute(stmt)
        archived = list(result.scalars().all())

    for mem in archived:
        should_heal = False
        reason_parts = []

        # Check lifecycle score
        if mem.lifecycle_score is not None and mem.lifecycle_score >= archive_cfg.promotion_threshold:
            should_heal = True
            reason_parts.append(f"lifecycle_score={mem.lifecycle_score:.3f}>={archive_cfg.promotion_threshold}")

        # Check recent access + reference count as proxy for rising citations
        if (
            mem.last_accessed_at
            and mem.last_accessed_at >= recent_cutoff
            and mem.referenced_count >= MIN_REF_DELTA
        ):
            should_heal = True
            reason_parts.append(f"recent_refs={mem.referenced_count}")

        if not should_heal:
            results["skipped"] += 1
            continue

        reason = f"self-heal: {'; '.join(reason_parts)}"
        new_tier = get_next_tier_up("archive")  # -> reference
        if not new_tier:
            continue

        success = await promote_episode(str(mem.id), new_tier, reason)
        if success:
            await log_tier_change(
                str(mem.id),
                "archive",
                new_tier,
                reason,
                "self_heal",
                lifecycle_score_before=mem.lifecycle_score,
            )
            results["healed"] += 1
            results["details"].append({
                "uuid": str(mem.id)[:8],
                "action": "self_heal",
                "from": "archive",
                "to": new_tier,
                "reason": reason,
                "lifecycle_score": mem.lifecycle_score,
            })
            logger.info("Self-healed memory %s: %s", str(mem.id)[:8], reason)

    logger.info(
        "Self-healing complete: %d healed, %d skipped",
        results["healed"],
        results["skipped"],
    )
    return results
