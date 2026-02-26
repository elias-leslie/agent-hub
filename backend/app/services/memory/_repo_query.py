"""List/filter/search query sub-repository for memories."""

from __future__ import annotations

import contextlib
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP


def _apply_list_order(stmt: Any, order_by: str) -> Any:
    """Apply ordering to a Memory select statement."""
    if order_by == "display_order":
        return stmt.order_by(Memory.display_order, Memory.created_at.desc())
    if order_by == "loaded_count":
        return stmt.order_by(Memory.loaded_count.desc())
    return stmt.order_by(Memory.created_at.desc())


def _build_list_conditions(
    *,
    status: str,
    scope: str | None,
    group_id: str | None,
    tier: int | str | None,
    memory_type: str | None,
    pinned: bool | None,
    auto_inject: bool | None,
    tags_include: list[str] | None,
    tags_exclude: list[str] | None,
    since: datetime | None,
) -> list[Any]:
    """Build SQLAlchemy WHERE conditions for list_by_scope_and_tier."""
    conditions: list[Any] = []
    if status:
        conditions.append(Memory.status == status)
    if scope:
        conditions.append(Memory.scope == scope)
    if group_id:
        conditions.append(Memory.group_id == group_id)
    if tier is not None:
        tier_num = TIER_MAP.get(tier, tier) if isinstance(tier, str) else tier
        conditions.append(Memory.tier == tier_num)
    if memory_type:
        conditions.append(Memory.memory_type == memory_type)
    if pinned is not None:
        conditions.append(Memory.pinned == pinned)
    if auto_inject is not None:
        conditions.append(Memory.auto_inject == auto_inject)
    if tags_include:
        conditions.append(Memory.tags.overlap(tags_include))
    if tags_exclude:
        conditions.append(~Memory.tags.overlap(tags_exclude))
    if since is not None:
        conditions.append(Memory.created_at >= since)
    return conditions


class QueryRepository:
    """Handles list, count, and lookup queries for memories."""

    async def list_by_scope_and_tier(
        self,
        *,
        scope: str | None = None,
        group_id: str | None = None,
        tier: int | str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        pinned: bool | None = None,
        auto_inject: bool | None = None,
        tags_include: list[str] | None = None,
        tags_exclude: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "display_order",
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """List memories with filtering and pagination."""
        conditions = _build_list_conditions(
            status=status,
            scope=scope,
            group_id=group_id,
            tier=tier,
            memory_type=memory_type,
            pinned=pinned,
            auto_inject=auto_inject,
            tags_include=tags_include,
            tags_exclude=tags_exclude,
            since=since,
        )
        stmt = select(Memory)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = _apply_list_order(stmt, order_by).limit(limit).offset(offset)

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_by_tier_names(
        self,
        *,
        tier_names: list[str],
        group_id: str | None = None,
        scope: str | None = None,
        status: str = "active",
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """List memories by tier name(s) — used for context injection."""
        tier_nums = [TIER_MAP[t] for t in tier_names if t in TIER_MAP]
        if not tier_nums:
            return []

        stmt = select(Memory).where(Memory.status == status, Memory.tier.in_(tier_nums))
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        stmt = stmt.order_by(Memory.display_order, Memory.created_at.desc())

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count(
        self,
        *,
        scope: str | None = None,
        group_id: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        db: AsyncSession | None = None,
    ) -> int:
        """Count memories matching criteria."""
        conditions: list[Any] = [Memory.status == status]
        if scope:
            conditions.append(Memory.scope == scope)
        if group_id:
            conditions.append(Memory.group_id == group_id)
        if memory_type:
            conditions.append(Memory.memory_type == memory_type)
        stmt = select(func.count(Memory.id)).where(and_(*conditions))

        if db:
            result = await db.execute(stmt)
            return result.scalar() or 0
        async with async_session() as session:
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def list_paginated(
        self,
        *,
        group_id: str | None = None,
        scope: str | None = None,
        scope_id: str | None = None,
        category: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Paginated list compatible with MemoryListResult format."""
        stmt = select(Memory).where(Memory.status == "active")
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if scope_id:
            stmt = stmt.where(Memory.scope_id == scope_id)
        if category:
            tier_num = TIER_MAP.get(category)
            if tier_num:
                stmt = stmt.where(Memory.tier == tier_num)
        if cursor:
            with contextlib.suppress(ValueError):
                stmt = stmt.where(Memory.created_at < datetime.fromisoformat(cursor))

        stmt = stmt.order_by(Memory.created_at.desc()).limit(limit + 1)

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())

        has_more = len(rows) > limit
        memories = rows[:limit]
        next_cursor = memories[-1].created_at.isoformat() if memories and has_more else None
        return {"memories": memories, "total": len(memories), "cursor": next_cursor, "has_more": has_more}

    async def text_search(
        self,
        query: str,
        *,
        group_id: str | None = None,
        scope: str | None = None,
        category: str | None = None,
        limit: int = 50,
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """Case-insensitive text search on content, name, and summary."""
        pattern = f"%{query}%"
        stmt = select(Memory).where(
            Memory.status == "active",
            or_(
                Memory.content.ilike(pattern),
                Memory.name.ilike(pattern),
                Memory.summary.ilike(pattern),
            ),
        )
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if category:
            tier_num = TIER_MAP.get(category)
            if tier_num:
                stmt = stmt.where(Memory.tier == tier_num)
        stmt = stmt.order_by(Memory.created_at.desc()).limit(limit)

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def resolve_uuid_prefix(
        self,
        prefix: str,
        *,
        group_id: str | None = None,
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        """Resolve an 8-char UUID prefix to a full UUID.

        Raises:
            ValueError: If prefix not found or ambiguous.
        """
        if "-" in prefix:
            return prefix  # Already a full UUID

        sql = text("""
            SELECT id::text AS full_uuid
            FROM memories
            WHERE REPLACE(id::text, '-', '') LIKE :prefix_pattern
              AND status = 'active'
            LIMIT 2
        """)
        params: dict[str, Any] = {"prefix_pattern": f"{prefix}%"}

        if db:
            result = await db.execute(sql, params)
            rows = result.mappings().all()
        else:
            async with async_session() as session:
                result = await session.execute(sql, params)
                rows = result.mappings().all()

        if not rows:
            raise ValueError(f"Memory not found with UUID prefix: {prefix}")
        if len(rows) > 1:
            uuids = [str(r["full_uuid"]) for r in rows]
            raise ValueError(
                f"Ambiguous UUID prefix '{prefix}' matches multiple memories: "
                f"{', '.join(u[:8] for u in uuids)}. Please provide more characters."
            )
        return str(rows[0]["full_uuid"])

    async def validate_ids(
        self,
        memory_ids: list[str],
        *,
        db: AsyncSession | None = None,
    ) -> set[str]:
        """Return set of valid memory IDs from the input list."""
        if not memory_ids:
            return set()
        uids = [_uuid.UUID(mid) for mid in memory_ids]
        stmt = select(Memory.id).where(Memory.id.in_(uids))

        if db:
            result = await db.execute(stmt)
        else:
            async with async_session() as session:
                result = await session.execute(stmt)

        return {str(row[0]) for row in result.all()}

    async def find_duplicate(
        self,
        content: str,
        *,
        group_id: str | None = None,
        window_minutes: int = 5,
        db: AsyncSession | None = None,
    ) -> str | None:
        """Find exact content duplicate within time window. Returns UUID or None."""
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        stmt = select(Memory.id).where(
            Memory.content == content,
            Memory.status == "active",
            Memory.created_at >= cutoff,
        )
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        stmt = stmt.limit(1)

        if db:
            result = await db.execute(stmt)
            row = result.scalar()
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                row = result.scalar()

        return str(row) if row else None
