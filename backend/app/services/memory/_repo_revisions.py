"""Revision-history helpers for memory repository CRUD."""

from __future__ import annotations

import hashlib
import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_actor import attribute, writer_columns
from app.db import async_session
from app.models.memory_unified import Memory, MemoryRevision

from .budget import count_tokens
from .embedder import get_embedder
from .fingerprint import content_fingerprint

logger = logging.getLogger(__name__)

# Bookkeeping columns a revision records but restore leaves alone on a live memory;
# a hard-deleted memory is recreated with them (``memory_created_at`` -> ``created_at``).
_ROW_STATE = ("sensitivity_tier", "review_status", "loaded_count", "referenced_count",
              "helpful_count", "harmful_count")


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
        """Persist an immutable snapshot for one memory state.

        Agent changes to delivered memories reach the owner through the context
        review queue (/context/changes), which reads these revisions.

        A delete revision takes the next version: a delete is a change, so a caller
        who saw the live memory at version N conflicts with it on restore.
        """
        revision = MemoryRevision(
            memory_id=memory.id,
            memory_uuid=str(memory.id),
            version=version or int(memory.version or 1) + (1 if action == "delete" else 0),
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
            render_mode=memory.render_mode,
            token_count=memory.token_count,
            status=memory.status,
            metadata_=dict(memory.metadata_ or {}),
            valid_at=memory.valid_at,
            content_hash=self._content_hash(memory.content),
            changed_by=attribute(changed_by),
            change_reason=change_reason,
            **writer_columns(),
            **{column: getattr(memory, column) for column in _ROW_STATE},
            memory_created_at=memory.created_at,
            # Wall-clock, not the transaction start, so revisions written in one transaction still order.
            created_at=datetime.now(UTC),
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
            revisions = list(result.scalars().all())
            for revision in revisions:
                session.expunge(revision)
            return revisions

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
            revision = result.scalar_one_or_none()
            if revision is not None:
                session.expunge(revision)
            return revision

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
        expected_version: int | None = None,
        changed_by: str | None = None,
        change_reason: str | None = None,
        db: AsyncSession | None = None,
    ) -> RestoredMemory | None:
        """Restore a memory to a historical revision, recreating it when it was hard-deleted.

        Every stored field of the revision comes back and the embedding is recomputed
        for the restored text; when the embedder fails the row is still written with no
        vector (stale: semantic search skips it, the next restore or content edit embeds
        it). The memory row is locked (``FOR UPDATE``) for the change;
        ``expected_version`` is the ``memories.version`` the caller saw (for a deleted
        memory, the version its delete revision recorded) and a mismatch raises
        ``RevisionConflictError`` without changing anything. A recreated memory gets
        sensitivity, review status, counters and created_at from its
        latest revision. Returns None when the revision does not exist.
        """
        uid = _uuid.UUID(str(memory_uuid))

        async def _restore_with_session(session: AsyncSession, commit: bool) -> RestoredMemory | None:
            revision = await self.get_revision(memory_uuid, revision_id, db=session)
            if revision is None:
                return None
            # Embed outside the row lock (it is a network call); recheck once locked.
            peek = (await session.execute(
                select(Memory.content, Memory.embedding.is_(None)).where(Memory.id == uid)
            )).first()
            embedding = None
            embed_tried = False
            retired = revision.status == "retired"  # tombstones keep no vector
            if not retired and _needs_embedding(revision, None if peek is None else (peek[0], bool(peek[1]))):
                embedding, embed_tried = await _embed_or_none(memory_uuid, revision.content), True

            memory = (await session.execute(
                select(Memory).where(Memory.id == uid).with_for_update()
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()
            latest_version = int((await session.execute(
                select(func.max(MemoryRevision.version)).where(MemoryRevision.memory_uuid == memory_uuid)
            )).scalar() or revision.version)
            current_version = int(memory.version or 1) if memory is not None else latest_version
            if expected_version is not None and current_version != expected_version:
                raise RevisionConflictError(memory_uuid, expected=expected_version, current=current_version)

            locked_state = None if memory is None else (memory.content, memory.embedding is None)
            if retired:
                embedding = None
            elif _needs_embedding(revision, locked_state):
                if embedding is None and not embed_tried:  # the row changed between the peek and the lock
                    embedding = await _embed_or_none(memory_uuid, revision.content)
            elif memory is not None:
                embedding = memory.embedding
            snapshot = _restore_snapshot(revision, embedding)

            now = datetime.now(UTC)
            if memory is None:
                row_state = await _latest_row_state(session, memory_uuid)
                memory = Memory(id=uid, version=latest_version + 1, updated_at=now,
                                **({"created_at": now} | row_state), **snapshot)
                session.add(memory)
                try:
                    await session.flush()
                except IntegrityError as exc:  # a concurrent restore recreated it first
                    raise RevisionConflictError(memory_uuid, expected=expected_version, current=None) from exc
                # Re-attach the history that the hard delete detached (memory_id SET NULL).
                await session.execute(
                    update(MemoryRevision)
                    .where(MemoryRevision.memory_uuid == memory_uuid, MemoryRevision.memory_id.is_(None))
                    .values(memory_id=uid)
                )
            else:
                for key, value in snapshot.items():
                    setattr(memory, key, value)
                memory.version = int(memory.version or 1) + 1
                memory.updated_at = now
                await session.flush()
            if memory.status == "active":
                # A restored active memory is no longer retired or merged into another.
                memory.retired_at = None
                memory.superseded_by = None
                await session.flush()

            restored = await self.record_revision(
                session,
                memory,
                action="restore",
                changed_by=changed_by,
                change_reason=change_reason or f"Restored revision {revision.id}",
            )
            if commit:
                await session.commit()
                await session.refresh(memory)
            return RestoredMemory(memory=memory, revision_id=str(restored.id), restored_from=str(revision.id),
                                  embedding_stale=not retired and embedding is None)

        if db:
            return await _restore_with_session(db, False)
        async with async_session() as session:
            return await _restore_with_session(session, True)


class RevisionConflictError(Exception):
    """The memory changed since the caller looked at it; reload before acting."""

    def __init__(self, memory_uuid: str, *, expected: int | None, current: int | None) -> None:
        self.memory_uuid, self.expected, self.current = memory_uuid, expected, current
        super().__init__(
            f"Memory {memory_uuid[:8]} changed (expected version {expected}, now {current}); reload before restoring"
        )


@dataclass(frozen=True)
class RestoredMemory:
    memory: Memory
    revision_id: str  # the new "restore" revision
    restored_from: str  # the revision whose state came back
    embedding_stale: bool = False  # saved without a vector because the embedder failed


def _needs_embedding(revision: MemoryRevision, current: tuple[str, bool] | None) -> bool:
    """A restored text needs a fresh embedding unless the row already holds that text and a vector."""
    if current is None:
        return True
    content, missing = current
    return missing or content != revision.content


async def _embed_or_none(memory_uuid: str, content: str) -> list[float] | None:
    """The restored text's vector, or None (left stale) when the embedder is down."""
    try:
        return await get_embedder().embed(content)
    except Exception as exc:  # any embedder failure leaves the vector stale; it never fails the restore
        logger.warning("Restore of memory %s saved without an embedding (embedder failed): %s", memory_uuid[:8], exc)
        return None


async def _latest_row_state(session: AsyncSession, memory_uuid: str) -> dict[str, object]:
    """Bookkeeping columns for a recreated memory: from the latest revision that recorded them,
    else (history older than that capture) created_at from the earliest revision."""
    state = (await session.execute(
        select(*(getattr(MemoryRevision, c) for c in _ROW_STATE), MemoryRevision.memory_created_at)
        .where(MemoryRevision.memory_uuid == memory_uuid, MemoryRevision.sensitivity_tier.is_not(None))
        .order_by(MemoryRevision.version.desc(), MemoryRevision.created_at.desc()).limit(1)
    )).first()
    if state is None:
        first = (await session.execute(
            select(func.min(MemoryRevision.created_at)).where(MemoryRevision.memory_uuid == memory_uuid)
        )).scalar()
        return {} if first is None else {"created_at": first}
    values = dict(zip(_ROW_STATE, state[:-1], strict=True))
    result: dict[str, object] = {column: value for column, value in values.items() if value is not None}
    if state[-1] is not None:
        result["created_at"] = state[-1]
    return result


def _restore_snapshot(revision: MemoryRevision, embedding: object) -> dict[str, object]:
    """Every memory column a revision stores, plus the values derived from its text."""
    return {
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
        "context_kind": revision.context_kind,
        "applicability": dict(revision.applicability or {}),
        "tier": revision.tier,
        "pinned": revision.pinned,
        "auto_inject": revision.auto_inject,
        "display_order": revision.display_order,
        "trigger_task_types": list(revision.trigger_task_types or []),
        "trigger_phases": list(revision.trigger_phases or []),
        "render_mode": revision.render_mode,
        "token_count": count_tokens(revision.content),
        "content_fingerprint": content_fingerprint(revision.content),
        "status": revision.status,
        "metadata_": dict(revision.metadata_ or {}),
        "valid_at": revision.valid_at,
        "embedding": embedding,
    }
