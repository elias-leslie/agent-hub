"""CRUD operations sub-repository for memories."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP, to_dict


class CrudRepository:
    """Handles create/read/update/delete for the memories table."""

    async def create(
        self,
        *,
        content: str,
        memory_type: str,
        scope: str = "global",
        scope_id: str | None = None,
        group_id: str | None = None,
        name: str | None = None,
        summary: str | None = None,
        source: str | None = None,
        source_description: str | None = None,
        embedding: list[float] | None = None,
        tier: int = 3,
        pinned: bool = False,
        auto_inject: bool = False,
        display_order: int = 50,
        tags: list[str] | None = None,
        trigger_task_types: list[str] | None = None,
        trigger_phases: list[str] | None = None,
        token_count: int | None = None,
        status: str = "active",
        metadata: dict | None = None,
        valid_at: datetime | None = None,
        id: _uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> Memory:
        """Create a new memory record."""
        now = datetime.now(UTC)
        memory = Memory(
            id=id or _uuid.uuid4(),
            content=content,
            name=name,
            summary=summary,
            embedding=embedding,
            memory_type=memory_type,
            scope=scope,
            scope_id=scope_id,
            group_id=group_id,
            source=source,
            source_description=source_description,
            tags=tags,
            tier=tier,
            pinned=pinned,
            auto_inject=auto_inject,
            display_order=display_order,
            trigger_task_types=trigger_task_types,
            trigger_phases=trigger_phases,
            token_count=token_count,
            status=status,
            metadata_=metadata or {},
            valid_at=valid_at or now,
            created_at=now,
            updated_at=now,
        )
        if db:
            db.add(memory)
            await db.flush()
            return memory
        async with async_session() as session:
            session.add(memory)
            await session.commit()
            return memory

    async def get(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> Memory | None:
        """Get a single memory by full UUID."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        if db:
            return await db.get(Memory, uid)
        async with async_session() as session:
            return await session.get(Memory, uid)

    async def get_as_dict(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """Get a single memory as a dict."""
        mem = await self.get(memory_id, db=db)
        if mem is None:
            return None
        return to_dict(mem)

    async def update(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update memory fields. Returns True if found and updated."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        if "metadata" in kwargs:
            kwargs["metadata_"] = kwargs.pop("metadata")
        if "injection_tier" in kwargs:
            kwargs["tier"] = TIER_MAP.get(kwargs.pop("injection_tier"), 3)
        kwargs["updated_at"] = datetime.now(UTC)

        stmt = update(Memory).where(Memory.id == uid).values(**kwargs)
        if db:
            result = await db.execute(stmt)
            return result.rowcount > 0  # type: ignore[union-attr]
        async with async_session() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0  # type: ignore[union-attr]

    async def delete(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> bool:
        """Hard-delete a memory. Returns True if found and deleted."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        stmt = delete(Memory).where(Memory.id == uid)
        if db:
            result = await db.execute(stmt)
            return result.rowcount > 0  # type: ignore[union-attr]
        async with async_session() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0  # type: ignore[union-attr]

    async def bulk_delete(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> int:
        """Delete multiple memories. Returns count deleted."""
        if not memory_ids:
            return 0
        uids = [_uuid.UUID(str(mid)) if isinstance(mid, str) else mid for mid in memory_ids]
        stmt = delete(Memory).where(Memory.id.in_(uids))
        if db:
            result = await db.execute(stmt)
            return result.rowcount  # type: ignore[union-attr]
        async with async_session() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount  # type: ignore[union-attr]
