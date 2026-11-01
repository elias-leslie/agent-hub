"""PostgreSQL contracts for memory and prompt history: every write path leaves a revision,
restore brings back every stored field under a row lock with a version check, and
revisions name their writer.

Runs against the explicit test database inside one rolled-back transaction with
private tables in a throwaway schema, so nothing persists.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
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


def _test_db_url() -> Any:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "History tests require a test database"
    return url


def _create_tables(sync_connection: Any) -> None:
    with_fks = (Memory.__table__, MemoryRevision.__table__)
    for table in (Agent.__table__, *with_fks, Prompt.__table__, PromptRevision.__table__):
        for column in table.columns:
            if isinstance(column.type, Enum):
                column.type.create(sync_connection, checkfirst=True)
        keep = None if table in with_fks or table is PromptRevision.__table__ else []
        sync_connection.execute(CreateTable(table, include_foreign_key_constraints=keep))
    sync_connection.execute(text(
        "CREATE TABLE context_deliveries (id serial PRIMARY KEY, generated_at timestamptz NOT NULL, payload_hash text,"
        " session_id text, surface text, work_role text, project_id text, coordinator boolean)"
    ))


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(_test_db_url())
    schema = f"revision_history_{uuid.uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        # public stays on the path for the pgvector type.
        await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        await connection.run_sync(_create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_engine() -> AsyncGenerator[AsyncEngine]:
    """Committed tables in a throwaway schema, so two connections can contend for one row lock."""
    url = _test_db_url()
    schema = f"revision_locks_{uuid.uuid4().hex}"
    # The schema name doubles as application_name, so a lock wait is found among this test's connections only.
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": f"{schema}, public", "application_name": schema}})
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.run_sync(_create_tables)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await engine.dispose()


async def _behind_row_lock(engine: AsyncEngine, work: Awaitable[Any]) -> asyncio.Task[Any]:
    """Start ``work`` and return once Postgres shows one of the engine's connections waiting on a lock."""
    task = asyncio.ensure_future(work)
    async with engine.connect() as watcher:
        for _ in range(200):
            waiting = (await watcher.execute(text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE application_name = current_setting('application_name') AND wait_event_type = 'Lock'"
            ))).scalar()
            if waiting or task.done():
                break
            await asyncio.sleep(0.025)
    assert not task.done(), "expected the second writer to wait on the row lock"
    return task


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

    with pytest.raises(RevisionConflictError) as conflict:  # saw the live v3; the delete since is v4
        await repo.restore_revision(str(memory_id), original.id, expected_version=3, db=pg_db)
    assert (conflict.value.expected, conflict.value.current) == (3, 4)
    restored = await repo.restore_revision(str(memory_id), original.id, expected_version=4, db=pg_db)

    assert restored is not None
    assert (restored.memory.content, restored.memory.context_kind, restored.memory.version) == (original.content, "policy", 5)
    history = await _revisions(pg_db, memory_id)
    assert [(r.action, r.version) for r in history] == [
        ("create", 1), ("update", 2), ("update", 3), ("delete", 4), ("restore", 5)]
    assert all(r.memory_id == memory_id for r in history)


async def test_recreated_memory_keeps_sensitivity_review_counters_and_created_at(pg_db: AsyncSession) -> None:
    repo = MemoryRepository()
    memory, original = await _memory_with_history(pg_db, repo)
    memory_id, created_at = memory.id, memory.created_at
    await repo.update(memory_id, db=pg_db, sensitivity_tier="confidential", review_status="clean", loaded_count=7,
                      referenced_count=3, helpful_count=2, harmful_count=1, lifecycle_score=0.75)
    assert await repo.delete(memory_id, db=pg_db)
    await pg_db.flush()
    pg_db.expunge_all()

    restored = await repo.restore_revision(str(memory_id), original.id, expected_version=5, db=pg_db)

    assert restored is not None
    row = restored.memory
    assert (row.sensitivity_tier, row.review_status, row.lifecycle_score) == ("confidential", "clean", 0.75)
    assert (row.loaded_count, row.referenced_count, row.helpful_count, row.harmful_count) == (7, 3, 2, 1)
    assert row.created_at == created_at


async def test_restore_saves_the_row_with_a_stale_embedding_when_the_embedder_is_down(
    pg_db: AsyncSession, fake_embedder: AsyncMock
) -> None:
    repo = MemoryRepository()
    memory, original = await _memory_with_history(pg_db, repo)
    fake_embedder.side_effect = RuntimeError("Gemini unavailable")

    restored = await repo.restore_revision(str(memory.id), original.id, expected_version=3, db=pg_db)

    assert restored is not None and restored.embedding_stale
    fake_embedder.assert_awaited_once_with(original.content)  # not retried under the row lock
    assert (restored.memory.content, restored.memory.embedding, restored.memory.version) == (original.content, None, 4)
    assert (await _revisions(pg_db, memory.id))[-1].action == "restore"


async def _committed_history(engine: AsyncEngine, repo: MemoryRepository) -> tuple[uuid.UUID, MemoryRevision]:
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        memory, original = await _memory_with_history(setup, repo)
        await setup.commit()
        return memory.id, original


async def test_update_waits_for_a_restore_holding_the_row_and_builds_on_it(pg_engine: AsyncEngine) -> None:
    repo = MemoryRepository()
    memory_id, original = await _committed_history(pg_engine, repo)

    async with AsyncSession(pg_engine) as owner, AsyncSession(pg_engine) as agent:
        await repo.restore_revision(str(memory_id), original.id, expected_version=3, db=owner)  # v4, lock held
        update = await _behind_row_lock(pg_engine, repo.update(memory_id, db=agent, summary="agent edit"))
        await owner.commit()
        assert await update
        await agent.commit()

    async with AsyncSession(pg_engine) as check:
        row = await check.get(Memory, memory_id)
        history = await _revisions(check, memory_id)
    assert row is not None
    assert (row.version, row.scope, row.tier, row.summary) == (5, "project", 2, "agent edit")
    latest = history[-1]
    assert (latest.action, latest.version, latest.scope, latest.tier, latest.summary) == (
        "update", 5, "project", 2, "agent edit")
    assert len({r.version for r in history}) == len(history)


async def test_delete_waits_for_a_restore_holding_the_row_and_records_what_it_deletes(pg_engine: AsyncEngine) -> None:
    repo = MemoryRepository()
    memory_id, original = await _committed_history(pg_engine, repo)

    async with AsyncSession(pg_engine) as owner, AsyncSession(pg_engine) as agent:
        await repo.restore_revision(str(memory_id), original.id, expected_version=3, db=owner)
        delete = await _behind_row_lock(pg_engine, repo.delete(memory_id, db=agent))
        await owner.commit()
        assert await delete
        await agent.commit()

    async with AsyncSession(pg_engine) as check:
        assert await check.get(Memory, memory_id) is None
        deleted = (await _revisions(check, memory_id))[-1]
    assert (deleted.action, deleted.version, deleted.content, deleted.scope) == ("delete", 5, original.content, "project")


async def test_retirement_skips_an_archive_promoted_while_it_waited_for_the_lock(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.memory.retirement import retire_stale_archives

    old = datetime.now(UTC) - timedelta(days=400)
    async with AsyncSession(pg_engine, expire_on_commit=False) as setup:
        stale = Memory(content="**Archive**: still wanted.", memory_type="reference", scope="global", tier=4,
                       status="active", version=1, created_at=old, updated_at=old, metadata_={})
        fresh = Memory(content="**Fresh**: keeps the system active.", memory_type="reference", scope="global", tier=3,
                       status="active", version=1, metadata_={})
        setup.add_all([stale, fresh])
        await setup.commit()
    monkeypatch.setattr("app.services.memory.retirement.async_session", lambda: AsyncSession(pg_engine))

    repo = MemoryRepository()
    async with AsyncSession(pg_engine) as owner:
        await repo.update(stale.id, db=owner, tier=2)  # promoted, lock held
        retire = await _behind_row_lock(pg_engine, retire_stale_archives())
        await owner.commit()
        result = await retire

    assert result["retired"] == 0
    async with AsyncSession(pg_engine) as check:
        row = await check.get(Memory, stale.id)
    assert row is not None
    assert (row.status, row.tier, row.content, row.version) == ("active", 2, "**Archive**: still wanted.", 2)


async def test_consolidation_archives_the_duplicate_with_a_revision(
    pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.memory import redundancy

    survivor = Memory(content="**Rule**: one.", memory_type="reference", scope="global", tier=3, status="active",
                      version=1, loaded_count=2, metadata_={})
    duplicate = Memory(content="**Rule**: one!", memory_type="reference", scope="global", tier=3, status="active",
                       version=3, loaded_count=5, metadata_={})
    pg_db.add_all([survivor, duplicate])
    await pg_db.flush()
    _use_session(monkeypatch, "app.services.memory.redundancy", pg_db)

    await redundancy._consolidate_pair(str(survivor.id), str(duplicate.id),
                                       {"similarity": 0.99, "id_b": str(duplicate.id), "tier_b": "reference"})

    assert (duplicate.status, duplicate.superseded_by, duplicate.version) == ("archived", survivor.id, 4)
    assert survivor.loaded_count == 7
    (revision,) = await _revisions(pg_db, duplicate.id)
    assert (revision.action, revision.status, revision.version, revision.changed_by) == (
        "consolidate", "archived", 4, "system:redundancy")


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
        "delete", "**Stale reference**: unused.", 6, "system:ttl-cleanup")  # a delete takes the next version


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


async def test_prompt_restore_of_a_deleted_agent_system_prompt_updates_its_agent(pg_db: AsyncSession) -> None:
    agent = Agent(slug="ctx-agent", name="Ctx agent", system_prompt="second", primary_model_id="m")
    pg_db.add(agent)
    await pg_db.flush()
    await create_prompt(pg_db, slug="ctx-agent-system", name="Ctx agent", content="first",
                        owner_agent_id=agent.id, prompt_type="agent_system")
    await update_prompt(pg_db, "ctx-agent-system", content="second")
    first = next(r for r in await list_prompt_revisions(pg_db, "ctx-agent-system") if r.content == "first")
    assert await delete_prompt(pg_db, "ctx-agent-system")

    restored = await restore_prompt_revision(pg_db, "ctx-agent-system", first.id)

    assert restored is not None and restored.content == "first"
    await pg_db.refresh(agent)
    assert agent.system_prompt == "first"
    owner_agent = restored.__dict__.get("owner_agent")  # what the API's cache invalidation reads
    assert owner_agent is not None and owner_agent.slug == "ctx-agent"


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


async def test_tier_changes_card_reads_optimizer_revisions(pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.memory import _analytics_top
    from app.services.memory.tier_operations import TIER_ACTOR

    repo = MemoryRepository()
    memory = await repo.create(
        content="**Tier card**: demoted by the optimizer.", memory_type="reference", scope="global",
        source="human", tier=2, embedding=VECTOR, db=pg_db,
    )
    await repo.update(memory.id, db=pg_db, tier=3, changed_by=TIER_ACTOR, change_reason="lifecycle 0.1")
    await repo.update(memory.id, db=pg_db, summary="owner edit, tier unchanged", changed_by="owner")
    _use_session(monkeypatch, "app.services.memory._analytics_top", pg_db)

    summary = cast(Any, await _analytics_top.get_tier_changes_summary(days=1))

    assert summary["total"] == 1
    assert summary["by_type"].keys() == {"demotion"}
    (move,) = summary["recent"]
    assert (move["episode_uuid"], move["old_tier"], move["new_tier"]) == (str(memory.id), "guardrail", "reference")
