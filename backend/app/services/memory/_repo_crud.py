"""CRUD operations sub-repository for memories."""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP, to_dict
from ._repo_revisions import RevisionRepository
from .fingerprint import content_fingerprint
from .memory_utils import parse_group_id

T = TypeVar("T")


def _resolve_scope_from_group_id(
    *,
    scope: str,
    scope_id: str | None,
    group_id: str | None,
) -> tuple[str, str | None]:
    """Derive canonical scope/scope_id from group_id; preserve explicit values."""
    if not group_id:
        return scope, scope_id
    if scope != "global" or scope_id is not None:
        return scope, scope_id

    derived_scope, derived_scope_id = parse_group_id(group_id)
    if derived_scope.value == "global":
        return scope, scope_id
    return derived_scope.value, derived_scope_id


def _build_memory(**kwargs: Any) -> Memory:
    """Instantiate a Memory from normalized create parameters."""
    now = datetime.now(UTC)
    return Memory(
        id=kwargs.get("id") or _uuid.uuid4(),
        version=1,
        content=kwargs["content"],
        content_fingerprint=kwargs.get("content_fingerprint_value")
        or content_fingerprint(kwargs["content"]),
        name=kwargs.get("name"),
        summary=kwargs.get("summary"),
        embedding=kwargs.get("embedding"),
        memory_type=kwargs["memory_type"],
        scope=kwargs["scope"],
        scope_id=kwargs.get("scope_id"),
        group_id=kwargs.get("group_id"),
        source=kwargs.get("source"),
        source_description=kwargs.get("source_description"),
        tags=kwargs.get("tags"),
        context_kind=kwargs.get("context_kind") or "reference",
        applicability=kwargs.get("applicability") or {},
        tier=kwargs.get("tier", 3),
        pinned=kwargs.get("pinned", False),
        auto_inject=kwargs.get("auto_inject", False),
        display_order=kwargs.get("display_order", 50),
        trigger_task_types=kwargs.get("trigger_task_types"),
        trigger_phases=kwargs.get("trigger_phases"),
        token_count=kwargs.get("token_count"),
        status=kwargs.get("status", "active"),
        review_status=kwargs.get("review_status", "pending"),
        sensitivity_tier=kwargs.get("sensitivity_tier", "normal"),
        metadata_=kwargs.get("metadata") or {},
        valid_at=kwargs.get("valid_at") or now,
        created_at=now,
        updated_at=now,
    )


def _normalize_update_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Rename metadata and auto-fill content fingerprint / tier mapping."""
    if "metadata" in kwargs:
        kwargs["metadata_"] = kwargs.pop("metadata")
    if "content" in kwargs and "content_fingerprint" not in kwargs:
        kwargs["content_fingerprint"] = content_fingerprint(str(kwargs["content"]))
    if "injection_tier" in kwargs:
        kwargs["tier"] = TIER_MAP.get(kwargs.pop("injection_tier"), 3)
    return kwargs


async def _with_session(
    db: AsyncSession | None,
    fn: Callable[[AsyncSession], Awaitable[T]],
    *,
    commit: bool = False,
) -> T:
    """Run an async callable with an existing session or a new one."""
    if db:
        return await fn(db)
    async with async_session() as session:
        result = await fn(session)
        if commit:
            await session.commit()
        return result


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
        resolved_scope, resolved_scope_id = _resolve_scope_from_group_id(
            scope=scope,
            scope_id=scope_id,
            group_id=group_id,
        )
        memory = _build_memory(
            id=id,
            content=content,
            content_fingerprint_value=content_fingerprint_value,
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
            context_kind=context_kind,
            applicability=applicability,
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
            metadata=metadata,
            valid_at=valid_at,
        )

        async def _create(session: AsyncSession) -> Memory:
            session.add(memory)
            await session.flush()
            await self.record_revision(
                session,
                memory,
                action="create",
                changed_by=changed_by,
                change_reason=change_reason or "Memory created",
            )
            return memory

        return await _with_session(db, _create, commit=db is None)

    async def get(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> Memory | None:
        """Get a single memory by full UUID."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id
        return await _with_session(db, lambda s: s.get(Memory, uid))  # type: ignore[arg-type,return-value]

    async def get_as_dict(
        self,
        memory_id: _uuid.UUID | str,
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """Get a single memory as a dict."""
        uid = _uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id

        async def _fetch(session: AsyncSession) -> dict[str, Any] | None:
            mem = await session.get(Memory, uid)
            return to_dict(mem) if mem is not None else None

        return await _with_session(db, _fetch)

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
        kwargs = _normalize_update_kwargs(kwargs)
        now = datetime.now(UTC)

        async def _update(session: AsyncSession) -> bool:
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
            return True

        return await _with_session(db, _update, commit=db is None)

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

        async def _delete(session: AsyncSession) -> bool:
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
            return True

        return await _with_session(db, _delete, commit=db is None)

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

        async def _execute(session: AsyncSession) -> int:
            result = await session.execute(stmt)
            return result.rowcount  # type: ignore[union-attr]

        return await _with_session(db, _execute, commit=db is None)
