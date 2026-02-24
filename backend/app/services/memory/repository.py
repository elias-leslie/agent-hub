"""Memory repository — CRUD + pgvector search on the unified memories table.

Replaces all Neo4j Cypher queries with SQLAlchemy async operations on PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

logger = logging.getLogger(__name__)

# Tier name ↔ numeric tier mapping
TIER_MAP = {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}
TIER_REVERSE = {v: k for k, v in TIER_MAP.items()}


class MemoryRepository:
    """Async repository for the unified memories table.

    All operations use SQLAlchemy async sessions against PostgreSQL + pgvector.
    """

    # ── CRUD ──────────────────────────────────────────────────────────────

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
        """Create a new memory record.

        Returns the created Memory ORM object.
        """
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
            valid_at=valid_at or datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        """Get a single memory as a dict (backward compat with Neo4j get_episode)."""
        mem = await self.get(memory_id, db=db)
        if mem is None:
            return None
        return self._to_dict(mem)

    async def update(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update memory fields. Returns True if found and updated."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        # Map 'metadata' kwarg to 'metadata_' column
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

    # ── List / Filter ─────────────────────────────────────────────────────

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
        """List memories with filtering.

        Args:
            scope: Filter by scope (e.g. 'global', 'project:agent-hub')
            group_id: Filter by group_id (backward compat)
            tier: Filter by tier number or name
            memory_type: Filter by memory_type
            status: Filter by status (default 'active')
            pinned: Filter by pinned flag
            auto_inject: Filter by auto_inject flag
            tags_include: Episode must have at least one of these tags
            tags_exclude: Episode must NOT have any of these tags
            since: Only return memories created after this datetime
            limit: Max results
            offset: Offset for pagination
            order_by: Sort field ('display_order', 'created_at', 'loaded_count')
            db: Optional session to use

        Returns:
            List of Memory objects
        """
        stmt = select(Memory)
        conditions = []

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

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Ordering
        if order_by == "display_order":
            stmt = stmt.order_by(Memory.display_order, Memory.created_at.desc())
        elif order_by == "created_at":
            stmt = stmt.order_by(Memory.created_at.desc())
        elif order_by == "loaded_count":
            stmt = stmt.order_by(Memory.loaded_count.desc())
        else:
            stmt = stmt.order_by(Memory.created_at.desc())

        stmt = stmt.limit(limit).offset(offset)

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
        """List memories by tier name(s) — used for context injection.

        Returns all active memories at the given tier(s) for a scope/group,
        ordered by display_order then created_at.
        """
        tier_nums = [TIER_MAP[t] for t in tier_names if t in TIER_MAP]
        if not tier_nums:
            return []

        stmt = select(Memory).where(
            Memory.status == status,
            Memory.tier.in_(tier_nums),
        )
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
        stmt = select(func.count(Memory.id))
        conditions = [Memory.status == status]
        if scope:
            conditions.append(Memory.scope == scope)
        if group_id:
            conditions.append(Memory.group_id == group_id)
        if memory_type:
            conditions.append(Memory.memory_type == memory_type)
        stmt = stmt.where(and_(*conditions))

        if db:
            result = await db.execute(stmt)
            return result.scalar() or 0
        async with async_session() as session:
            result = await session.execute(stmt)
            return result.scalar() or 0

    # ── Paginated List (backward compat with list_episodes_paginated) ─────

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
            try:
                cursor_dt = datetime.fromisoformat(cursor)
                stmt = stmt.where(Memory.created_at < cursor_dt)
            except ValueError:
                pass

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

        return {
            "memories": memories,
            "total": len(memories),
            "cursor": memories[-1].created_at.isoformat() if memories and has_more else None,
            "has_more": has_more,
        }

    # ── Search ────────────────────────────────────────────────────────────

    async def semantic_search(
        self,
        query_embedding: list[float],
        *,
        scope: str | None = None,
        group_id: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        limit: int = 10,
        min_score: float = 0.0,
        exclude_ids: list[_uuid.UUID] | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search using pgvector cosine similarity.

        Returns list of dicts with memory data + relevance_score, ordered by similarity.
        """
        # Use raw SQL for pgvector cosine distance operator
        # 1 - (embedding <=> query_vec) gives cosine similarity (0 to 1)
        vec_str = "[" + ",".join(str(f) for f in query_embedding) + "]"

        conditions = ["status = :status", "embedding IS NOT NULL"]
        params: dict[str, Any] = {"status": status, "vec": vec_str, "limit": limit}

        if scope:
            conditions.append("scope = :scope")
            params["scope"] = scope
        if group_id:
            conditions.append("group_id = :group_id")
            params["group_id"] = group_id
        if memory_type:
            conditions.append("memory_type = :memory_type")
            params["memory_type"] = memory_type
        if min_score > 0:
            conditions.append("(1 - (embedding <=> CAST(:vec AS vector))) >= :min_score")
            params["min_score"] = min_score
        if exclude_ids:
            conditions.append("id NOT IN :exclude_ids")
            params["exclude_ids"] = tuple(exclude_ids)

        where = " AND ".join(conditions)

        sql = text(f"""
            SELECT id, content, name, summary, memory_type, scope, scope_id,
                   group_id, source, source_description, tags,
                   tier, pinned, auto_inject, display_order,
                   loaded_count, referenced_count, helpful_count, harmful_count,
                   status, token_count, metadata, valid_at,
                   created_at, updated_at, last_accessed_at,
                   (1 - (embedding <=> CAST(:vec AS vector))) AS relevance_score
            FROM memories
            WHERE {where}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """)

        if db:
            result = await db.execute(sql, params)
            rows = result.mappings().all()
        else:
            async with async_session() as session:
                result = await session.execute(sql, params)
                rows = result.mappings().all()

        return [dict(row) for row in rows]

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
        """Case-insensitive text search on content, name, summary, and tier."""
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

    # ── UUID Prefix Resolution ────────────────────────────────────────────

    async def resolve_uuid_prefix(
        self,
        prefix: str,
        *,
        group_id: str | None = None,
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        """Resolve an 8-char UUID prefix to a full UUID.

        Args:
            prefix: 8-char hex UUID prefix (e.g. '7126dedf')
            group_id: Optional group_id filter
            scope: Optional scope filter

        Returns:
            Full UUID string

        Raises:
            ValueError: If prefix not found or ambiguous
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

    # ── Tier Optimization ─────────────────────────────────────────────────

    async def find_demotion_candidates(
        self,
        *,
        min_loads: int = 200,
        grace_period_hours: int = 48,
        min_age_days: int = 7,
        harmful_threshold: int = 3,
        demotion_threshold: float = 0.15,
        ghost_ratio_threshold: float = 10.0,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Find memories eligible for tier demotion."""
        now = datetime.now(UTC)
        cutoff_grace = now - timedelta(hours=grace_period_hours)
        cutoff_age = now - timedelta(days=min_age_days)

        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier.in_([1, 2]),  # Only mandates and guardrails
            Memory.pinned == False,  # noqa: E712
            Memory.created_at < cutoff_grace,
            or_(
                # Low utility
                and_(
                    Memory.loaded_count >= min_loads,
                    Memory.created_at < cutoff_age,
                ),
                # Harmful
                Memory.harmful_count >= harmful_threshold,
            ),
        )

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())

        candidates = []
        for mem in rows:
            utility = mem.utility_score
            ghost = mem.loaded_count / (mem.referenced_count + 1)
            reason = None

            if mem.harmful_count >= harmful_threshold:
                reason = f"harmful_count={mem.harmful_count}"
            elif ghost >= ghost_ratio_threshold:
                reason = f"ghost_ratio={ghost:.1f}"
            elif utility < demotion_threshold:
                reason = f"utility_score={utility:.3f}"
            else:
                continue  # Doesn't actually qualify

            candidates.append({
                "uuid": str(mem.id),
                "name": mem.name,
                "injection_tier": mem.injection_tier,
                "loaded_count": mem.loaded_count,
                "referenced_count": mem.referenced_count,
                "helpful_count": mem.helpful_count,
                "harmful_count": mem.harmful_count,
                "utility_score": utility,
                "ghost_ratio": ghost,
                "reason": reason,
            })
        return candidates

    async def find_promotion_candidates(
        self,
        *,
        min_refs: int = 20,
        min_age_days: int = 7,
        helpful_threshold: int = 5,
        promotion_threshold: float = 0.70,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Find memories eligible for tier promotion."""
        cutoff_age = datetime.now(UTC) - timedelta(days=min_age_days)

        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier.in_([2, 3]),  # guardrails → mandates, references → guardrails
            or_(
                # High utility
                and_(
                    Memory.referenced_count >= min_refs,
                    Memory.created_at < cutoff_age,
                ),
                # Helpful
                Memory.helpful_count >= helpful_threshold,
            ),
        )

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())

        candidates = []
        for mem in rows:
            utility = mem.utility_score
            reason = None

            if mem.helpful_count >= helpful_threshold:
                reason = f"helpful_count={mem.helpful_count}"
            elif utility >= promotion_threshold:
                reason = f"utility_score={utility:.3f}"
            else:
                continue

            candidates.append({
                "uuid": str(mem.id),
                "name": mem.name,
                "injection_tier": mem.injection_tier,
                "loaded_count": mem.loaded_count,
                "referenced_count": mem.referenced_count,
                "helpful_count": mem.helpful_count,
                "harmful_count": mem.harmful_count,
                "utility_score": utility,
                "reason": reason,
            })
        return candidates

    # ── Usage Tracking ────────────────────────────────────────────────────

    async def increment_loaded(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """Increment loaded_count for injected memories."""
        if not memory_ids:
            return
        uids = [_uuid.UUID(str(mid)) if isinstance(mid, str) else mid for mid in memory_ids]
        now = datetime.now(UTC)
        stmt = (
            update(Memory)
            .where(Memory.id.in_(uids))
            .values(
                loaded_count=Memory.loaded_count + 1,
                last_accessed_at=now,
            )
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
        uids = [_uuid.UUID(str(mid)) if isinstance(mid, str) else mid for mid in memory_ids]
        stmt = update(Memory).where(Memory.id.in_(uids)).values(
            referenced_count=Memory.referenced_count + 1,
        )
        if db:
            await db.execute(stmt)
        else:
            async with async_session() as session:
                await session.execute(stmt)
                await session.commit()

    async def increment_helpful(
        self, memory_id: _uuid.UUID | str, *, db: AsyncSession | None = None
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
        self, memory_id: _uuid.UUID | str, *, db: AsyncSession | None = None
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

    # ── Batch Operations ──────────────────────────────────────────────────

    async def batch_get(
        self,
        memory_ids: list[_uuid.UUID | str],
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Get multiple memories as dicts keyed by UUID string."""
        if not memory_ids:
            return {}
        uids = [_uuid.UUID(str(mid)) if isinstance(mid, str) else mid for mid in memory_ids]
        stmt = select(Memory).where(Memory.id.in_(uids))

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())

        return {str(mem.id): self._to_dict(mem) for mem in rows}

    async def batch_update_properties(
        self,
        updates: list[dict[str, Any]],
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, bool]:
        """Batch update memory properties. Each dict must have 'uuid' key."""
        results: dict[str, bool] = {}
        for upd in updates:
            uid = upd.pop("uuid", None)
            if not uid:
                continue
            try:
                ok = await self.update(uid, db=db, **upd)
                results[uid] = ok
            except Exception as e:
                logger.error("Batch update failed for %s: %s", uid[:8] if uid else "?", e)
                results[uid] = False
        return results

    # ── Triggered References ──────────────────────────────────────────────

    async def get_triggered_references(
        self,
        task_type: str,
        *,
        group_id: str = "global",
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """Get reference-tier memories triggered by a task_type."""
        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier == TIER_MAP["reference"],
            Memory.trigger_task_types.any(task_type),
        )
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

    async def get_phase_triggered_references(
        self,
        phase: str,
        *,
        group_id: str = "global",
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """Get reference-tier memories triggered by a subtask phase."""
        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier == TIER_MAP["reference"],
            Memory.trigger_phases.any(phase),
        )
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

    # ── Stats / Analytics ─────────────────────────────────────────────────

    async def get_stats(
        self,
        *,
        scope: str | None = None,
        group_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Get memory stats — total, by_category, by_scope."""
        conditions = [Memory.status == "active"]
        if scope:
            conditions.append(Memory.scope == scope)
        if group_id:
            conditions.append(Memory.group_id == group_id)

        where = and_(*conditions)

        # Total count
        total_stmt = select(func.count(Memory.id)).where(where)

        # Count by tier (= category)
        tier_stmt = (
            select(Memory.tier, func.count(Memory.id))
            .where(where)
            .group_by(Memory.tier)
        )

        # Count by scope
        scope_stmt = (
            select(Memory.scope, func.count(Memory.id))
            .where(where)
            .group_by(Memory.scope)
        )

        # Last updated
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

        return {
            "total": total,
            "by_category": by_category,
            "by_scope": by_scope,
            "last_updated": last,
        }

    # ── Cleanup ───────────────────────────────────────────────────────────

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

        # Check last activity
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

            # Delete stale reference-tier memories (never delete mandates/guardrails)
            del_stmt = delete(Memory).where(
                Memory.tier >= 3,  # reference or archive only
                Memory.status == "active",
                Memory.pinned == False,  # noqa: E712
                or_(
                    Memory.last_accessed_at < cutoff,
                    and_(Memory.last_accessed_at.is_(None), Memory.created_at < cutoff),
                ),
            )
            if group_id:
                del_stmt = del_stmt.where(Memory.group_id == group_id)

            result = await session.execute(del_stmt)
            await session.commit()

            return {
                "deleted": result.rowcount,
                "skipped": False,
                "cutoff": cutoff.isoformat(),
            }

    # ── Deduplication ─────────────────────────────────────────────────────

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

    # ── Validation ────────────────────────────────────────────────────────

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

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(mem: Memory) -> dict[str, Any]:
        """Convert Memory ORM object to dict (backward compat)."""
        return {
            "uuid": str(mem.id),
            "content": mem.content,
            "name": mem.name,
            "summary": mem.summary,
            "memory_type": mem.memory_type,
            "scope": mem.scope,
            "scope_id": mem.scope_id,
            "group_id": mem.group_id,
            "source": mem.source,
            "source_description": mem.source_description,
            "tags": mem.tags or [],
            "injection_tier": mem.injection_tier,
            "tier": mem.tier,
            "pinned": mem.pinned,
            "auto_inject": mem.auto_inject,
            "display_order": mem.display_order,
            "trigger_task_types": mem.trigger_task_types or [],
            "trigger_phases": mem.trigger_phases or [],
            "loaded_count": mem.loaded_count,
            "referenced_count": mem.referenced_count,
            "helpful_count": mem.helpful_count,
            "harmful_count": mem.harmful_count,
            "utility_score": mem.utility_score,
            "status": mem.status,
            "token_count": mem.token_count,
            "metadata": mem.metadata_ or {},
            "valid_at": mem.valid_at,
            "created_at": mem.created_at,
            "updated_at": mem.updated_at,
            "last_accessed_at": mem.last_accessed_at,
        }


def get_memory_repository() -> MemoryRepository:
    """Get a MemoryRepository instance."""
    return MemoryRepository()
