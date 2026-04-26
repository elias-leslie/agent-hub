"""CRUD operations sub-repository for memories."""

from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory, MemoryRevision

from ._repo_helpers import TIER_MAP, to_dict
from .fingerprint import content_fingerprint
from .memory_utils import parse_group_id


def _resolve_scope_from_group_id(
    *,
    scope: str,
    scope_id: str | None,
    group_id: str | None,
) -> tuple[str, str | None]:
    """Derive canonical scope/scope_id from group_id when caller uses defaults.

    If caller already provided a non-global scope or explicit scope_id, preserve it.
    """
    if not group_id:
        return scope, scope_id
    if scope != "global" or scope_id is not None:
        return scope, scope_id

    derived_scope, derived_scope_id = parse_group_id(group_id)
    if derived_scope.value == "global":
        return scope, scope_id
    return derived_scope.value, derived_scope_id


class CrudRepository:
    """Handles create/read/update/delete for the memories table."""

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
        context_kind: str | None = None,
        applicability: dict | None = None,
        tier: int = 3,
        pinned: bool = False,
        auto_inject: bool = False,
        display_order: int = 50,
        tags: list[str] | None = None,
        trigger_task_types: list[str] | None = None,
        trigger_phases: list[str] | None = None,
        token_count: int | None = None,
        status: str = "active",
        review_status: str = "pending",
        sensitivity_tier: str = "normal",
        content_fingerprint_value: str | None = None,
        metadata: dict | None = None,
        valid_at: datetime | None = None,
        id: _uuid.UUID | None = None,
        changed_by: str | None = None,
        change_reason: str | None = None,
        db: AsyncSession | None = None,
    ) -> Memory:
        """Create a new memory record."""
        now = datetime.now(UTC)
        resolved_scope, resolved_scope_id = _resolve_scope_from_group_id(
            scope=scope,
            scope_id=scope_id,
            group_id=group_id,
        )
        memory = Memory(
            id=id or _uuid.uuid4(),
            version=1,
            content=content,
            content_fingerprint=content_fingerprint_value or content_fingerprint(content),
            name=name,
            summary=summary,
            embedding=embedding,
            memory_type=memory_type,
            scope=resolved_scope,
            scope_id=resolved_scope_id,
            group_id=group_id,
            source=source,
            source_description=source_description,
            tags=tags,
            context_kind=context_kind or "reference",
            applicability=applicability or {},
            tier=tier,
            pinned=pinned,
            auto_inject=auto_inject,
            display_order=display_order,
            trigger_task_types=trigger_task_types,
            trigger_phases=trigger_phases,
            token_count=token_count,
            status=status,
            review_status=review_status,
            sensitivity_tier=sensitivity_tier,
            metadata_=metadata or {},
            valid_at=valid_at or now,
            created_at=now,
            updated_at=now,
        )
        if db:
            db.add(memory)
            await db.flush()
            await self.record_revision(
                db,
                memory,
                action="create",
                changed_by=changed_by,
                change_reason=change_reason or "Memory created",
            )
            return memory
        async with async_session() as session:
            session.add(memory)
            await session.flush()
            await self.record_revision(
                session,
                memory,
                action="create",
                changed_by=changed_by,
                change_reason=change_reason or "Memory created",
            )
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
        changed_by: str | None = None,
        change_reason: str | None = None,
        action: str = "update",
        db: AsyncSession | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update memory fields. Returns True if found and updated."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        if "metadata" in kwargs:
            kwargs["metadata_"] = kwargs.pop("metadata")
        if "content" in kwargs and "content_fingerprint" not in kwargs:
            kwargs["content_fingerprint"] = content_fingerprint(str(kwargs["content"]))
        if "injection_tier" in kwargs:
            kwargs["tier"] = TIER_MAP.get(kwargs.pop("injection_tier"), 3)
        now = datetime.now(UTC)

        async def _update_with_session(session: AsyncSession, commit: bool) -> bool:
            memory = await session.get(Memory, uid)
            if memory is None:
                return False
            for key, value in kwargs.items():
                setattr(memory, key, value)
            memory.version = int(memory.version or 1) + 1
            memory.updated_at = now
            await session.flush()
            await self.record_revision(
                session,
                memory,
                action=action,
                changed_by=changed_by,
                change_reason=change_reason or "Memory updated",
            )
            if commit:
                await session.commit()
            return True

        if db:
            return await _update_with_session(db, False)
        async with async_session() as session:
            return await _update_with_session(session, True)

    async def delete(
        self,
        memory_id: _uuid.UUID | str,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
        db: AsyncSession | None = None,
    ) -> bool:
        """Hard-delete a memory. Returns True if found and deleted."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id

        async def _delete_with_session(session: AsyncSession, commit: bool) -> bool:
            memory = await session.get(Memory, uid)
            if memory is None:
                return False
            await self.record_revision(
                session,
                memory,
                action="delete",
                changed_by=changed_by,
                change_reason=change_reason or "Memory deleted",
            )
            await session.delete(memory)
            if commit:
                await session.commit()
            return True

        if db:
            return await _delete_with_session(db, False)
        async with async_session() as session:
            return await _delete_with_session(session, True)

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

            memory = await session.get(Memory, uid)
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
            now = datetime.now(UTC)
            if memory is None:
                latest_version = revision.version + 1
                memory = Memory(
                    id=uid,
                    version=latest_version,
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
