"""List/filter/search query sub-repository for memories."""

from __future__ import annotations

import contextlib
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP
from .fingerprint import content_fingerprint


def _parse_pagination_cursor(cursor: str) -> tuple[datetime, _uuid.UUID | None]:
    """Parse a pagination cursor into timestamp and optional UUID tie-breaker."""
    if "|" not in cursor:
        return datetime.fromisoformat(cursor), None

    timestamp_raw, uuid_raw = cursor.split("|", 1)
    return datetime.fromisoformat(timestamp_raw), _uuid.UUID(uuid_raw)


def _build_pagination_cursor(timestamp: datetime, memory_id: _uuid.UUID) -> str:
    """Build a stable pagination cursor using the active sort timestamp plus UUID."""
    return f"{timestamp.isoformat()}|{memory_id}"


def _resolve_sort_column(order_by: str):
    """Return the timestamp column used for ordering and cursor pagination."""
    if order_by == "created_at":
        return Memory.created_at
    return Memory.updated_at


def _apply_list_order(stmt: Any, order_by: str, sort_order: str = "desc") -> Any:
    """Apply ordering to a Memory select statement."""
    if order_by == "display_order":
        return stmt.order_by(Memory.display_order, Memory.created_at.desc())
    sort_column = _resolve_sort_column(order_by)
    if sort_order == "asc":
        return stmt.order_by(sort_column.asc(), Memory.id.asc())
    return stmt.order_by(sort_column.desc(), Memory.id.desc())


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
        sort_order: str = "desc",
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
        stmt = _apply_list_order(stmt, order_by, sort_order).limit(limit).offset(offset)

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

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
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

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
        order_by: str = "updated_at",
        sort_order: str = "desc",
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Paginated list compatible with MemoryListResult format."""
        sort_column = _resolve_sort_column(order_by)
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
                cursor_time, cursor_id = _parse_pagination_cursor(cursor)
                if cursor_id is None:
                    if sort_order == "asc":
                        stmt = stmt.where(sort_column > cursor_time)
                    else:
                        stmt = stmt.where(sort_column < cursor_time)
                else:
                    if sort_order == "asc":
                        stmt = stmt.where(
                            or_(
                                sort_column > cursor_time,
                                and_(sort_column == cursor_time, Memory.id > cursor_id),
                            )
                        )
                    else:
                        stmt = stmt.where(
                            or_(
                                sort_column < cursor_time,
                                and_(sort_column == cursor_time, Memory.id < cursor_id),
                            )
                        )

        stmt = _apply_list_order(stmt, order_by, sort_order).limit(limit + 1)

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                session.expunge_all()

        has_more = len(rows) > limit
        memories = rows[:limit]
        next_cursor = None
        if memories and has_more:
            last = memories[-1]
            last_timestamp = getattr(last, order_by, None) or last.updated_at or last.created_at
            next_cursor = _build_pagination_cursor(last_timestamp, last.id)
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
        """Ranked full-text search with ILIKE fallback."""
        search_document = func.to_tsvector(
            "english",
            func.concat_ws(" ", Memory.name, Memory.summary, Memory.content),
        )
        search_query = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(search_document, search_query)
        stmt = select(Memory).where(
            Memory.status == "active",
            search_document.op("@@")(search_query),
        )
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if category:
            tier_num = TIER_MAP.get(category)
            if tier_num:
                stmt = stmt.where(Memory.tier == tier_num)
        stmt = stmt.order_by(desc(rank), Memory.updated_at.desc()).limit(limit)

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                session.expunge_all()
        if rows:
            return rows

        pattern = f"%{query}%"
        fallback_stmt = select(Memory).where(
            Memory.status == "active",
            or_(
                Memory.content.ilike(pattern),
                Memory.name.ilike(pattern),
                Memory.summary.ilike(pattern),
            ),
        )
        if group_id:
            fallback_stmt = fallback_stmt.where(Memory.group_id == group_id)
        if scope:
            fallback_stmt = fallback_stmt.where(Memory.scope == scope)
        if category:
            tier_num = TIER_MAP.get(category)
            if tier_num:
                fallback_stmt = fallback_stmt.where(Memory.tier == tier_num)
        fallback_stmt = fallback_stmt.order_by(Memory.updated_at.desc()).limit(limit)

        if db:
            result = await db.execute(fallback_stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(fallback_stmt)
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

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
            # Validate it looks like a real UUID before accepting
            import re

            if re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                prefix,
            ):
                return prefix
            raise ValueError(
                f"Invalid UUID format: {prefix}. "
                "Expected 8-char prefix or full UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."
            )

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
            return {str(row[0]) for row in result.all()}
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
        """Find normalized content duplicate. Returns UUID or None."""
        fingerprint = content_fingerprint(content)
        fingerprint_stmt = select(Memory.id).where(
            Memory.content_fingerprint == fingerprint,
            Memory.status == "active",
        )
        if group_id:
            fingerprint_stmt = fingerprint_stmt.where(Memory.group_id == group_id)
        fingerprint_stmt = fingerprint_stmt.order_by(Memory.created_at.asc()).limit(1)

        if db:
            result = await db.execute(fingerprint_stmt)
            row = result.scalar()
        else:
            async with async_session() as session:
                result = await session.execute(fingerprint_stmt)
                row = result.scalar()
        if row:
            return str(row)

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
