"""Graduated retirement pipeline — replaces hard-delete TTL cleanup.

Lifecycle:
  Active -> Archive: handled by tier optimizer (daily)
  Archive -> Tombstone: this module (after 180 days with no access)
  Tombstone: never deleted — audit trail forever

Tombstoning clears content + embedding but preserves metadata
(id, name, timestamps, counters, tier history).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update

from app.db import async_session
from app.models.memory_unified import Memory

logger = logging.getLogger(__name__)

RETIREMENT_DAYS = 180  # archive must be untouched for this many days


async def retire_stale_archives(
    *,
    retirement_days: int = RETIREMENT_DAYS,
) -> dict[str, Any]:
    """Tombstone archived memories that haven't been accessed.

    Instead of deleting, we:
    1. Set status = 'retired' (new tombstone status)
    2. Clear content and embedding (free storage)
    3. Set retired_at timestamp
    4. Preserve all metadata, counters, and name for audit

    Safety: if system is inactive (no active memories created recently),
    skip to prevent mass retirement.

    Returns dict with {retired, skipped, reason}.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=retirement_days)

    async with async_session() as session:
        # Safety guard: check system is active
        last_stmt = select(func.max(Memory.created_at)).where(Memory.status == "active")
        last = (await session.execute(last_stmt)).scalar()

        if last and last < cutoff:
            return {
                "retired": 0,
                "skipped": True,
                "reason": "System inactive — skipping to prevent mass retirement",
            }

        # Find stale archives
        stale_stmt = select(Memory).where(
            and_(
                Memory.tier == 4,  # archive
                Memory.status == "active",
                Memory.pinned == False,  # noqa: E712
                Memory.superseded_by.is_(None),  # not already consolidated
                or_(
                    Memory.last_accessed_at < cutoff,
                    and_(Memory.last_accessed_at.is_(None), Memory.created_at < cutoff),
                ),
            )
        )
        result = await session.execute(stale_stmt)
        stale = list(result.scalars().all())

        if not stale:
            return {"retired": 0, "skipped": False, "reason": "No stale archives found"}

        stale_ids = [mem.id for mem in stale]

        # Tombstone: clear content/embedding, set retired status
        await session.execute(
            update(Memory)
            .where(Memory.id.in_(stale_ids))
            .values(
                status="retired",
                content="[retired]",
                embedding=None,
                retired_at=now,
            )
        )
        await session.commit()

        logger.info("Retired %d stale archived memories (>%d days without access)", len(stale_ids), retirement_days)
        return {
            "retired": len(stale_ids),
            "skipped": False,
            "cutoff": cutoff.isoformat(),
        }
