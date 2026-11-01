"""PostgreSQL contracts for memory and prompt history: every write path leaves a revision,
restore brings back every stored field under a row lock with a version check, and
revisions name their writer.

Runs against the explicit test database inside one rolled-back transaction with
private tables in a throwaway schema, so nothing persists.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.core.request_actor import RequestWriter, bind_request_writer
from app.models.agent import Agent
from app.models.memory_unified import Memory, MemoryRevision
from app.models.prompt import Prompt, PromptRevision
from app.services import context_writer
from app.services.memory._repo_revisions import RevisionConflictError
from app.services.memory.repository import MemoryRepository
from app.services.prompt_service import (
    PromptRevisionConflictError,
    create_prompt,
    delete_prompt,
    list_prompt_revisions,
    restore_prompt_revision,
    update_prompt,
)

pytestmark = pytest.mark.integration

VECTOR = [0.25] * 768


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "History tests require a test database"
    engine = create_async_engine(url)
    schema = f"revision_history_{uuid.uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        # public stays on the path for the pgvector type.
        await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))

        def create_tables(sync_connection: Any) -> None:
            with_fks = (Memory.__table__, MemoryRevision.__table__)
            for table in (Agent.__table__, *with_fks, Prompt.__table__, PromptRevision.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                keep = None if table in with_fks or table is PromptRevision.__table__ else []
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=keep))

        await connection.run_sync(create_tables)
        await connection.execute(text(
            "CREATE TABLE context_deliveries (id serial PRIMARY KEY, generated_at timestamptz NOT NULL, payload_hash text,"
            " session_id text, surface text, work_role text, project_id text, coordinator boolean)"
        ))
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    embed = AsyncMock(return_value=VECTOR)
    monkeypatch.setattr("app.services.memory._repo_revisions.get_embedder", lambda: MagicMock(embed=embed))
    return embed


def _use_session(monkeypatch: pytest.MonkeyPatch, module: str, db: AsyncSession) -> None:
    @asynccontextmanager
    async def same() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(f"{module}.async_session", same)


async def _revisions(db: AsyncSession, memory_id: uuid.UUID) -> list[MemoryRevision]:
    rows = await db.execute(
        select(MemoryRevision).where(MemoryRevision.memory_uuid == str(memory_id))
        .order_by(MemoryRevision.version, MemoryRevision.created_at)
    )
    return list(rows.scalars())


async def _memory_with_history(db: AsyncSession, repo: MemoryRepository) -> tuple[Memory, MemoryRevision]:
    """A policy memory at v1, then an update to v2 changing every delivery switch."""
    memory = await repo.create(
        content="**Restore check**: keep the original wording.", memory_type="reference", scope="project",
        scope_id="agent-hub", group_id="project-agent-hub", name="restore-check", summary="original",
        source="human", tags=["one"], context_kind="policy", applicability={"consumer_profiles": ["agent_startup"]},
        tier=2, pinned=True, display_order=10, trigger_task_types=["implementation"], trigger_phases=["start"],
        metadata={"compact_content": "original compact"}, embedding=VECTOR, db=db,
    )
    await repo.update(memory.id, db=db, render_mode="compact")
    (original,) = [r for r in await _revisions(db, memory.id) if r.version == 2]
    await repo.update(
        memory.id, db=db, content="**Restore check**: replaced wording.", summary="changed", tags=["two"],
        context_kind="reference", applicability={}, render_mode="full", scope="global", scope_id=None,
        tier=3, pinned=False, display_order=50, trigger_task_types=[], trigger_phases=[],
        metadata={"compact_content": "changed compact"}, embedding=[0.5] * 768,
    )
    await db.refresh(memory)
    assert memory.version == 3
    return memory, original


async def test_restore_brings_back_every_field_and_re_embeds(pg_db: AsyncSession, fake_embedder: AsyncMock) -> None:
    repo = MemoryRepository()
    memory, original = await _memory_with_history(pg_db, repo)
    bind_request_writer(RequestWriter(kind="agent", delivery="d" * 64, session="aico-widget-lane"))

    statements: list[str] = []
    real_execute = pg_db.execute

    async def spy(statement: Any, *args: Any, **kwargs: Any) -> Any:
        statements.append(str(statement.compile(dialect=postgresql.dialect())))
        return await real_execute(statement, *args, **kwargs)

    pg_db.execute = spy  # type: ignore[method-assign]
    restored = await repo.restore_revision(str(memory.id), original.id, expected_version=3, db=pg_db)
    pg_db.execute = real_execute  # type: ignore[method-assign]

    assert restored is not None
    row = restored.memory
    assert any("FROM memories" in s and "FOR UPDATE" in s for s in statements)
    assert (row.content, row.summary, row.tags) == (original.content, "original", ["one"])
    assert (row.context_kind, row.applicability, row.render_mode) == ("policy", {"consumer_profiles": ["agent_startup"]}, "compact")
    assert (row.scope, row.scope_id, row.tier, row.pinned, row.display_order) == ("project", "agent-hub", 2, True, 10)
    assert (row.trigger_task_types, row.trigger_phases) == (["implementation"], ["start"])
    assert (row.metadata_ or {})["compact_content"] == "original compact"
    fake_embedder.assert_awaited_once_with(original.content)
    assert list(row.embedding) == pytest.approx(VECTOR)
    assert row.version == 4
    restore = (await _revisions(pg_db, memory.id))[-1]
    assert (restore.id, restore.action, restore.version) == (restored.revision_id, "restore", 4)
    assert (restore.writer_kind, restore.writer_session) == ("agent", "aico-widget-lane")
    assert restored.restored_from == original.id


async def test_restore_refuses_a_newer_unseen_change_and_changes_nothing(pg_db: AsyncSession, fake_embedder: AsyncMock) -> None:
    repo = MemoryRepository()
    memory, original = await _memory_with_history(pg_db, repo)

    with pytest.raises(RevisionConflictError) as conflict:
        await repo.restore_revision(str(memory.id), original.id, expected_version=2, db=pg_db)

    assert (conflict.value.expected, conflict.value.current) == (2, 3)
    await pg_db.refresh(memory)
    assert (memory.version, memory.content) == (3, "**Restore check**: replaced wording.")
    assert [r.action for r in await _revisions(pg_db, memory.id)] == ["create", "update", "update"]


async def test_restore_recreates_a_hard_deleted_memory_and_reattaches_its_history(pg_db: AsyncSession) -> None:
    repo = MemoryRepository()
    memory, original = await _memory_with_history(pg_db, repo)
    memory_id = memory.id
    assert await repo.delete(memory_id, db=pg_db)
    await pg_db.flush()
    pg_db.expunge_all()
    assert all(r.memory_id is None for r in await _revisions(pg_db, memory_id))

    with pytest.raises(RevisionConflictError):  # the delete revision recorded version 3
        await repo.restore_revision(str(memory_id), original.id, expected_version=2, db=pg_db)
    restored = await repo.restore_revision(str(memory_id), original.id, expected_version=3, db=pg_db)

    assert restored is not None
    assert (restored.memory.content, restored.memory.context_kind, restored.memory.version) == (original.content, "policy", 4)
    history = await _revisions(pg_db, memory_id)
    assert [r.action for r in history] == ["create", "update", "update", "delete", "restore"]
    assert all(r.memory_id == memory_id for r in history)


async def test_retirement_keeps_the_text_in_history_and_restore_brings_it_back(
    pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.memory.retirement import retire_stale_archives

    old = datetime.now(UTC) - timedelta(days=400)
    stale = Memory(content="**Archive**: old procedure text.", memory_type="reference", scope="global", tier=4,
                   status="active", version=1, embedding=VECTOR, created_at=old, updated_at=old, metadata_={})
    fresh = Memory(content="**Fresh**: keeps the system active.", memory_type="reference", scope="global", tier=3,
                   status="active", version=1, metadata_={})
    pg_db.add_all([stale, fresh])
    await pg_db.flush()
    _use_session(monkeypatch, "app.services.memory.retirement", pg_db)

    assert (await retire_stale_archives())["retired"] == 1

    await pg_db.refresh(stale)
    assert (stale.status, stale.content, stale.embedding, stale.version) == ("retired", "[retired]", None, 2)
    snapshot, retire = await _revisions(pg_db, stale.id)
    assert (snapshot.action, snapshot.content, snapshot.version) == ("snapshot", "**Archive**: old procedure text.", 1)
    assert (retire.action, retire.content, retire.changed_by, retire.writer_kind) == ("retire", "[retired]", "system:retirement", "system")

    restored = await MemoryRepository().restore_revision(str(stale.id), snapshot.id, expected_version=2, db=pg_db)
    assert restored is not None
    assert (restored.memory.status, restored.memory.content, restored.memory.retired_at) == (
        "active", "**Archive**: old procedure text.", None)
    assert restored.memory.embedding is not None


async def test_ttl_cleanup_deletes_with_revisions(pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    old = datetime.now(UTC) - timedelta(days=60)
    stale = Memory(content="**Stale reference**: unused.", memory_type="reference", scope="global", tier=3,
                   status="active", version=5, created_at=old, updated_at=old, metadata_={})
    fresh = Memory(content="**Fresh**: keeps the system active.", memory_type="reference", scope="global", tier=3,
                   status="active", version=1, metadata_={})
    pg_db.add_all([stale, fresh])
    await pg_db.flush()
    stale_id = stale.id
    _use_session(monkeypatch, "app.services.memory._repo_analytics", pg_db)

    result = await MemoryRepository().cleanup_stale(ttl_days=30)

    assert result["deleted"] == 1
    assert await pg_db.get(Memory, stale_id) is None
    (deleted,) = await _revisions(pg_db, stale_id)
    assert (deleted.action, deleted.content, deleted.version, deleted.changed_by) == (
        "delete", "**Stale reference**: unused.", 5, "system:ttl-cleanup")


async def test_scope_normalization_writes_a_revision_per_row(pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.memory.scope_normalization import normalize_legacy_scope_rows

    legacy = Memory(content="a", memory_type="reference", scope="project:neri", tier=3, status="active", version=1, metadata_={})
    grouped = Memory(content="b", memory_type="reference", scope="global", group_id="project-aico", tier=3,
                     status="active", version=1, metadata_={})
    clean = Memory(content="c", memory_type="reference", scope="global", tier=3, status="active", version=1, metadata_={})
    pg_db.add_all([legacy, grouped, clean])
    await pg_db.flush()
    _use_session(monkeypatch, "app.services.memory.scope_normalization", pg_db)

    counts = await normalize_legacy_scope_rows()

    assert counts == {"legacy_prefixed_scope": 1, "global_scope_project_group": 1, "project_scope_missing_scope_id": 0}
    for row in (legacy, grouped, clean):
        await pg_db.refresh(row)
    assert (legacy.scope, legacy.scope_id, legacy.group_id, legacy.version) == ("project", "neri", "project-neri", 2)
    assert (grouped.scope, grouped.scope_id, grouped.version) == ("project", "aico", 2)
    assert clean.version == 1
    (revision,) = await _revisions(pg_db, legacy.id)
    assert (revision.action, revision.scope, revision.changed_by) == ("scope_normalize", "project", "system:scope-normalization")
    assert await _revisions(pg_db, clean.id) == []


async def test_review_decision_lands_in_history(pg_db: AsyncSession) -> None:
    from app.services.memory._review_agent_apply import apply_review_decision
    from app.services.memory._review_agent_decisions import MemoryReviewDecision

    memory = Memory(content="**Rule**: session-only advice.", memory_type="reference", scope="global", tier=3,
                    status="active", version=1, metadata_={})
    pg_db.add(memory)
    await pg_db.flush()
    checks = {key: "pass" for key in ("currency", "correctness", "conflict", "lifecycle", "appropriateness")}
    decision = MemoryReviewDecision(
        uuid=str(memory.id), decision="retarget", review_status="clean", confidence=0.95,
        reason="project only", checks=checks, suggested_applicability={"scope": "project", "scope_id": "neri"},
    )

    revision = await apply_review_decision(pg_db, memory, decision, datetime.now(UTC))

    assert (memory.scope, memory.scope_id, memory.version) == ("project", "neri", 2)
    assert (revision.action, revision.scope, revision.version, revision.changed_by) == ("review", "project", 2, "agent:memory-reviewer")


async def test_prompt_restore_recreates_a_deleted_prompt_and_checks_the_latest_revision(pg_db: AsyncSession) -> None:
    await create_prompt(pg_db, slug="ctx-check", name="Ctx check", content="first", is_global=True)
    await update_prompt(pg_db, "ctx-check", content="second")
    revisions = await list_prompt_revisions(pg_db, "ctx-check")
    first = next(r for r in revisions if r.content == "first")
    latest = revisions[0]

    with pytest.raises(PromptRevisionConflictError):
        await restore_prompt_revision(pg_db, "ctx-check", first.id, expected_revision_id=first.id)
    assert await delete_prompt(pg_db, "ctx-check")
    with pytest.raises(PromptRevisionConflictError):  # the delete revision is newer than what we saw
        await restore_prompt_revision(pg_db, "ctx-check", first.id, expected_revision_id=latest.id)

    deleted = (await list_prompt_revisions(pg_db, "ctx-check"))[0]
    restored = await restore_prompt_revision(pg_db, "ctx-check", first.id, expected_revision_id=deleted.id)

    assert restored is not None
    assert (restored.content, restored.is_global) == ("first", True)
    history = await list_prompt_revisions(pg_db, "ctx-check")
    assert history[0].action == "restore"
    assert all(r.prompt_id == restored.id for r in history)


async def test_revision_writer_resolves_through_the_context_delivery(pg_db: AsyncSession) -> None:
    now = datetime.now(UTC)
    await pg_db.execute(text(
        "INSERT INTO context_deliveries (generated_at, payload_hash, session_id, surface, work_role, project_id, coordinator) VALUES"
        " (:old, 'h1', 'aico-widget-other', 'codex', 'review', 'neri', false),"
        " (:now, 'h1', 'aico-widget-lane', 'claude_code', 'implementation', 'agent-hub', false),"
        " (:now, 'h2', 'aico-widget-coord', 'claude_code', 'coordinator', 'summitflow', true)"
    ), {"old": now - timedelta(hours=1), "now": now})
    repo = MemoryRepository()
    bind_request_writer(RequestWriter(kind="agent", delivery="h1", session="aico-widget-lane"))
    memory = await repo.create(content="**Lane**: a lane wrote this.", memory_type="reference", db=pg_db)
    bind_request_writer(RequestWriter(kind="agent", delivery="h-unknown", session="aico-widget-coord"))
    await repo.update(memory.id, db=pg_db, summary="coordinator edit")
    bind_request_writer(RequestWriter(kind="owner"))
    await repo.update(memory.id, db=pg_db, summary="owner edit")

    writers = await context_writer.resolve_writers(pg_db, await _revisions(pg_db, memory.id))

    lane, coordinator, owner = writers
    assert (lane.kind, lane.session, lane.harness, lane.work_role, lane.project, lane.resolved) == (
        "agent", "aico-widget-lane", "claude_code", "implementation", "agent-hub", True)
    assert (coordinator.harness, coordinator.work_role, coordinator.coordinator) == ("claude_code", "coordinator", True)
    assert (owner.kind, owner.harness, owner.resolved) == ("owner", None, False)
