"""Analytics, stats, and cleanup sub-repository for memories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_REVERSE
from ._repo_revisions import RevisionRepository


class AnalyticsRepository:
    """Handles stats, cleanup, and analytical queries for memories."""

    async def get_stats(
        self,
        *,
        scope: str | None = None,
        group_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Get memory stats — total, by_category, by_scope."""
        conditions: list[Any] = [Memory.status == "active"]
        if scope:
            conditions.append(Memory.scope == scope)
        if group_id:
            conditions.append(Memory.group_id == group_id)

        where = and_(*conditions)
        total_stmt = select(func.count(Memory.id)).where(where)
        tier_stmt = select(Memory.tier, func.count(Memory.id)).where(where).group_by(Memory.tier)
        scope_stmt = select(Memory.scope, func.count(Memory.id)).where(where).group_by(Memory.scope)
        last_stmt = select(func.max(Memory.updated_at)).where(where)

        if db:
            total = (await db.execute(total_stmt)).scalar() or 0
            tier_rows = (await db.execute(tier_stmt)).all()
            scope_rows = (await db.execute(scope_stmt)).all()
            last = (await db.execute(last_stmt)).scalar()
        else:
            async with async_session() as session:
                total = (await session.execute(total_stmt)).scalar() or 0
                tier_rows = (await session.execute(tier_stmt)).all()
                scope_rows = (await session.execute(scope_stmt)).all()
                last = (await session.execute(last_stmt)).scalar()

        by_category = [
            {"category": TIER_REVERSE.get(tier, "unknown"), "count": cnt}
            for tier, cnt in tier_rows
        ]
        by_scope = [{"scope": s, "count": cnt} for s, cnt in scope_rows]
        return {"total": total, "by_category": by_category, "by_scope": by_scope, "last_updated": last}

    async def cleanup_stale(
        self,
        *,
        group_id: str | None = None,
        ttl_days: int = 30,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Delete stale memories not accessed within TTL.

        Preserves safety: if system inactive >= ttl_days, skip cleanup.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=ttl_days)

        last_stmt = select(func.max(Memory.created_at)).where(Memory.status == "active")
        if group_id:
            last_stmt = last_stmt.where(Memory.group_id == group_id)

        async with async_session() as session:
            last = (await session.execute(last_stmt)).scalar()

            if last and last < cutoff:
                return {
                    "deleted": 0,
                    "skipped": True,
                    "reason": "System inactive — skipping to prevent mass deletion",
                }

            stale_stmt = select(Memory).where(
                Memory.tier >= 3,
                Memory.status == "active",
                Memory.pinned == False,  # noqa: E712
                or_(
                    Memory.last_accessed_at < cutoff,
                    and_(Memory.last_accessed_at.is_(None), Memory.created_at < cutoff),
                ),
            ).with_for_update()
            if group_id:
                stale_stmt = stale_stmt.where(Memory.group_id == group_id)

            # Each delete leaves a revision so the memory can be reviewed and restored.
            revisions = RevisionRepository()
            stale = list((await session.execute(stale_stmt)).scalars().all())
            for memory in stale:
                await revisions.record_revision(
                    session, memory, action="delete", changed_by="system:ttl-cleanup",
                    change_reason=f"Not accessed for {ttl_days} days",
                )
                await session.delete(memory)
            await session.commit()

        return {"deleted": len(stale), "skipped": False, "cutoff": cutoff.isoformat()}
