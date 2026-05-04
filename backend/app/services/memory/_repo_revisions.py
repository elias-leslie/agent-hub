"""Revision-history helpers for memory repository CRUD."""

from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory, MemoryRevision


class RevisionRepository:
    """Handles immutable revision snapshots and revision lookup."""

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def record_revision(
        self,
        db: AsyncSession,
        memory: Memory,
        *,
        action: str,
        changed_by: str | None = None,
        change_reason: str | None = None,
        version: int | None = None,
    ) -> MemoryRevision:
        """Persist an immutable snapshot for one memory state."""
        revision = MemoryRevision(
            memory_id=memory.id,
            memory_uuid=str(memory.id),
            version=version or int(memory.version or 1),
            action=action,
            content=memory.content,
            name=memory.name,
            summary=memory.summary,
            memory_type=memory.memory_type,
            scope=memory.scope,
            scope_id=memory.scope_id,
            group_id=memory.group_id,
            source=memory.source,
            source_description=memory.source_description,
            tags=list(memory.tags or []),
            context_kind=memory.context_kind,
            applicability=dict(memory.applicability or {}),
            tier=memory.tier,
            pinned=bool(memory.pinned),
            auto_inject=bool(memory.auto_inject),
            display_order=int(memory.display_order or 50),
            trigger_task_types=list(memory.trigger_task_types or []),
            trigger_phases=list(memory.trigger_phases or []),
            token_count=memory.token_count,
            status=memory.status,
            metadata_=dict(memory.metadata_ or {}),
            valid_at=memory.valid_at,
            content_hash=self._content_hash(memory.content),
            changed_by=changed_by,
            change_reason=change_reason,
        )
        db.add(revision)
        await db.flush()
        return revision

    async def list_revisions(
        self,
        memory_uuid: str,
        *,
        limit: int = 20,
        db: AsyncSession | None = None,
    ) -> list[MemoryRevision]:
        """List recent revisions for a memory UUID."""
        stmt = (
            select(MemoryRevision)
            .where(MemoryRevision.memory_uuid == memory_uuid)
            .order_by(MemoryRevision.created_at.desc())
            .limit(limit)
        )
        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_revision(
        self,
        memory_uuid: str,
        revision_id: str,
        *,
        db: AsyncSession | None = None,
    ) -> MemoryRevision | None:
        """Fetch a specific revision for one memory UUID."""
        resolved_revision_id = revision_id
        normalized_revision_id = revision_id.replace("-", "")
        if len(normalized_revision_id) != 32:
            resolved_revision_id = await self.resolve_revision_id_prefix(
                memory_uuid,
                revision_id,
                db=db,
            )

        stmt = select(MemoryRevision).where(
            MemoryRevision.memory_uuid == memory_uuid,
            MemoryRevision.id == resolved_revision_id,
        )
        if db:
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        async with async_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def resolve_revision_id_prefix(
        self,
        memory_uuid: str,
        prefix: str,
        *,
        db: AsyncSession | None = None,
    ) -> str:
        """Resolve a revision UUID prefix within one memory's history."""
        normalized_prefix = prefix.replace("-", "")
        stmt = (
            select(cast(MemoryRevision.id, String))
            .where(
                MemoryRevision.memory_uuid == memory_uuid,
                func.replace(cast(MemoryRevision.id, String), "-", "").like(f"{normalized_prefix}%"),
            )
            .limit(2)
        )
        if db:
            result = await db.execute(stmt)
            rows = [str(value) for value in result.scalars().all()]
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = [str(value) for value in result.scalars().all()]

        if not rows:
            raise ValueError(
                f"Revision not found with UUID prefix '{prefix}' for memory {memory_uuid[:8]}"
            )
        if len(rows) > 1:
            raise ValueError(
                f"Ambiguous revision prefix '{prefix}' for memory {memory_uuid[:8]}: "
                f"{', '.join(row[:8] for row in rows)}. Please provide more characters."
            )
        return rows[0]

    async def resolve_revision_memory_uuid_prefix(
        self,
        prefix: str,
        *,
        db: AsyncSession | None = None,
    ) -> str:
        """Resolve a memory UUID prefix from revision history."""
        if "-" in prefix:
            return prefix

        stmt = (
            select(MemoryRevision.memory_uuid)
            .where(func.replace(MemoryRevision.memory_uuid, "-", "").like(f"{prefix}%"))
            .distinct()
            .limit(2)
        )
        if db:
            result = await db.execute(stmt)
            rows = [str(value) for value in result.scalars().all()]
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = [str(value) for value in result.scalars().all()]

        if not rows:
            raise ValueError(f"Memory not found with UUID prefix: {prefix}")
        if len(rows) > 1:
            raise ValueError(
                f"Ambiguous UUID prefix '{prefix}' matches multiple memories: "
                f"{', '.join(row[:8] for row in rows)}. Please provide more characters."
            )
        return rows[0]

    async def restore_revision(
        self,
        memory_uuid: str,
        revision_id: str,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
        db: AsyncSession | None = None,
    ) -> Memory | None:
        """Restore a memory to a specific historical revision."""
        uid = _uuid.UUID(str(memory_uuid))

        async def _restore_with_session(session: AsyncSession, commit: bool) -> Memory | None:
            revision = await self.get_revision(memory_uuid, revision_id, db=session)
            if revision is None:
                return None

            snapshot = {
                "content": revision.content,
                "name": revision.name,
                "summary": revision.summary,
                "memory_type": revision.memory_type,
                "scope": revision.scope,
                "scope_id": revision.scope_id,
                "group_id": revision.group_id,
                "source": revision.source,
                "source_description": revision.source_description,
                "tags": list(revision.tags or []),
                "tier": revision.tier,
                "pinned": revision.pinned,
                "auto_inject": revision.auto_inject,
                "display_order": revision.display_order,
                "trigger_task_types": list(revision.trigger_task_types or []),
                "trigger_phases": list(revision.trigger_phases or []),
                "token_count": revision.token_count,
                "status": revision.status,
                "metadata_": dict(revision.metadata_ or {}),
                "valid_at": revision.valid_at,
            }
            memory = await session.get(Memory, uid)
            now = datetime.now(UTC)
            if memory is None:
                memory = Memory(
                    id=uid,
                    version=revision.version + 1,
                    created_at=now,
                    updated_at=now,
                    **snapshot,
                )
                session.add(memory)
            else:
                for key, value in snapshot.items():
                    setattr(memory, key, value)
                memory.version = int(memory.version or 1) + 1
                memory.updated_at = now

            await session.flush()
            await self.record_revision(
                session,
                memory,
                action="restore",
                changed_by=changed_by,
                change_reason=change_reason or f"Restored revision {revision_id}",
            )
            if commit:
                await session.commit()
                await session.refresh(memory)
            return memory

        if db:
            return await _restore_with_session(db, False)
        async with async_session() as session:
            return await _restore_with_session(session, True)
