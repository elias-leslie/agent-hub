"""CRUD operations sub-repository for memories."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP, to_dict
from ._repo_revisions import RevisionRepository
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


class CrudRepository(RevisionRepository):
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
