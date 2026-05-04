"""Usage tracking and batch operations sub-repository for memories."""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import to_dict, to_uuids

logger = logging.getLogger(__name__)


class TrackingRepository:
    """Handles usage counters and batch operations for memories."""

    async def increment_loaded(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """Increment loaded_count for injected memories."""
        if not memory_ids:
            return
        uids = to_uuids(memory_ids)
        stmt = (
            update(Memory)
            .where(Memory.id.in_(uids))
            .values(loaded_count=Memory.loaded_count + 1, last_accessed_at=datetime.now(UTC))
        )
        if db:
            await db.execute(stmt)
        else:
            async with async_session() as session:
                await session.execute(stmt)
                await session.commit()

    async def increment_referenced(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """Increment referenced_count for cited memories."""
        if not memory_ids:
            return
        uids = to_uuids(memory_ids)
        stmt = update(Memory).where(Memory.id.in_(uids)).values(
            referenced_count=Memory.referenced_count + 1,
            last_accessed_at=datetime.now(UTC),
        )
        if db:
            await db.execute(stmt)
        else:
            async with async_session() as session:
                await session.execute(stmt)
                await session.commit()

    async def increment_helpful(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """Increment helpful_count."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        stmt = update(Memory).where(Memory.id == uid).values(
            helpful_count=Memory.helpful_count + 1,
        )
        if db:
            await db.execute(stmt)
        else:
            async with async_session() as session:
                await session.execute(stmt)
                await session.commit()

    async def increment_harmful(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """Increment harmful_count."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        stmt = update(Memory).where(Memory.id == uid).values(
            harmful_count=Memory.harmful_count + 1,
        )
        if db:
            await db.execute(stmt)
        else:
            async with async_session() as session:
                await session.execute(stmt)
                await session.commit()

    async def batch_get(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Get multiple memories as dicts keyed by UUID string."""
        if not memory_ids:
            return {}
        uids = to_uuids(memory_ids)
        stmt = select(Memory).where(Memory.id.in_(uids))

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
            return {str(mem.id): to_dict(mem) for mem in rows}
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                return {str(mem.id): to_dict(mem) for mem in rows}

    async def batch_update_properties(
        self,
        updates: list[dict[str, Any]],
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, bool]:
        """Batch update memory properties. Each dict must have 'uuid' key."""
        results: dict[str, bool] = {}
        for upd in updates:
            uid = upd.get("uuid")
            if not uid:
                continue
            # Build kwargs without 'uuid' — don't pop() since caller may read it after.
            kwargs = {k: v for k, v in upd.items() if k != "uuid"}
            try:
                ok = await self.update(uid, db=db, **kwargs)  # type: ignore[attr-defined]
                results[uid] = ok
            except Exception as e:
                logger.error("Batch update failed for %s: %s", uid[:8] if uid else "?", e)
                results[uid] = False
        return results
