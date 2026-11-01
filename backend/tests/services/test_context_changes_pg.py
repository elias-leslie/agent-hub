"""PostgreSQL contracts for the context review queue and keep / rework / refuse.

Agents keep writing; the owner reviews afterwards. Owner writes never queue, every other non-archive change does,
one row per target; refuse undoes through the locked, version-checked restore and a change the reviewer did not see
returns a conflict that changes nothing.

Runs against the explicit test database: private tables in a throwaway schema, rolled back or dropped.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Enum, make_url, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.core.request_actor import RequestWriter, bind_request_writer
from app.models.agent import Agent
from app.models.context_change_review import ContextChangeReview
from app.models.context_governance import ContextRecord
from app.models.context_observability import ContextDelivery
from app.models.memory_unified import Memory, MemoryRevision
from app.models.prompt import Prompt, PromptRevision
from app.models.runtime_context import RuntimeContextOverride
from app.models.subscription_accounting import UsageSession
from app.services.api_key_auth import require_api_key
from app.services.context_changes import (
    DecideRequest,
    ReviewConflict,
    ReviewItem,
    ReworkRequest,
    build_queue,
    keep,
    refuse,
    rework,
)
from app.services.context_changes.decisions import Edit, Narrow
from app.services.memory.repository import MemoryRepository
from app.services.prompt_service import create_prompt, update_prompt

pytestmark = pytest.mark.integration

VECTOR = [0.25] * 768
HASH = "h" * 64
LANE = RequestWriter(kind="agent", delivery=HASH, session="aico-widget-lane")
OTHER_LANE = RequestWriter(kind="agent", delivery="o" * 64, session="aico-widget-other")
OWNER = RequestWriter(kind="owner")


def _test_db_url() -> Any:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Review tests require a test database"
    return url


def _create_tables(sync_connection: Any) -> None:
    with_fks = (Memory.__table__, MemoryRevision.__table__, PromptRevision.__table__)
    tables = (Agent.__table__, Memory.__table__, MemoryRevision.__table__, Prompt.__table__, PromptRevision.__table__,
              ContextRecord.__table__, RuntimeContextOverride.__table__, ContextChangeReview.__table__,
              ContextDelivery.__table__, UsageSession.__table__)
    for table in tables:
        for column in table.columns:
            if isinstance(column.type, Enum):
                column.type.create(sync_connection, checkfirst=True)
        sync_connection.execute(CreateTable(table, include_foreign_key_constraints=None if table in with_fks else []))


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(_test_db_url())
    schema = f"context_changes_{uuid.uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))  # public: pgvector
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
    schema = f"context_changes_locks_{uuid.uuid4().hex}"
    engine = create_async_engine(_test_db_url(), connect_args={
        "server_settings": {"search_path": f"{schema}, public", "application_name": schema}})
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.run_sync(_create_tables)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await engine.dispose()


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """No embedder or Nightshift calls; the embedder returns a fixed vector."""
    embed = AsyncMock(return_value=VECTOR)
    monkeypatch.setattr("app.services.memory._repo_revisions.get_embedder", lambda: MagicMock(embed=embed))
    monkeypatch.setattr("app.services.global_context_notes.send_note", AsyncMock())
    return embed


def _as(writer: RequestWriter) -> None:
    bind_request_writer(writer)


async def _memory(db: AsyncSession, content: str, *, writer: RequestWriter, scope: str = "global",
                  scope_id: str | None = None, tier: int = 3, metadata: dict[str, Any] | None = None) -> Memory:
    _as(writer)
    return await MemoryRepository().create(
        content=content, memory_type="reference", scope=scope, scope_id=scope_id, tier=tier, embedding=VECTOR,
        name=content[:20], summary=content[:40], context_kind="policy", metadata=metadata, db=db)


async def _update(db: AsyncSession, memory: Memory, *, writer: RequestWriter, **changes: Any) -> None:
    _as(writer)
    assert await MemoryRepository().update(memory.id, db=db, **changes)
    if memory in db:
        await db.refresh(memory)


async def _delivery(db: AsyncSession, *, blocks: list[tuple[str, str]], surface: str = "claude_code",
                    role: str | None = "implementation", project: str | None = "agent-hub",
                    session: str = "aico-widget-lane", payload_hash: str = HASH, profile: str = "agent_startup") -> str:
    delivery_id = uuid.uuid4().hex
    db.add(ContextDelivery(
        delivery_id=delivery_id, generated_at=datetime.now(UTC) - timedelta(hours=1), source="api", surface=surface,
        profile=profile, project_id=project, session_id=session, work_role=role, coordinator=False, consumer_tags=[],
        est_tokens=100, payload_hash=payload_hash, rendered_chars=400, by_scope={},
        blocks=[{"source_type": t, "source_id": i, "tokens": 50} for t, i in blocks]))
    await db.flush()
    return delivery_id


def _row(queue: Any, key: str) -> Any:
    return next(r for r in queue.rows if r.key == key)


def _item(row: Any, **overrides: Any) -> ReviewItem:
    fields = {"target_kind": row.target_kind, "target_id": row.target_id, "through_revision": row.through_revision,
              "expected_version": row.version}
    return ReviewItem(**(fields | overrides))


async def _revisions(db: AsyncSession, memory_id: uuid.UUID) -> list[MemoryRevision]:
    return list((await db.execute(select(MemoryRevision).where(MemoryRevision.memory_uuid == str(memory_id))
                                  .order_by(MemoryRevision.created_at))).scalars())


async def test_queue_folds_agent_changes_and_never_queues_owner_or_archive_writes(pg_db: AsyncSession) -> None:
    lane = await _memory(pg_db, "**Haiku testers**: test UI with Haiku agents.", writer=LANE,
                         metadata={"last_review": {"decision": "archive", "confidence": 0.93,
                                                   "reason": "only relevant to one session"}})
    await _update(pg_db, lane, writer=LANE, content="**Haiku testers**: always test UI with Haiku agents first.")
    await _memory(pg_db, "**Owner rule**: the owner wrote this.", writer=OWNER)
    await _memory(pg_db, "**Episode**: archived from the start.", writer=LANE, tier=4)
    legacy = await _memory(pg_db, "**Legacy**: written before writer capture.", writer=LANE)
    await pg_db.execute(text("UPDATE memory_revisions SET writer_kind = NULL WHERE memory_uuid = :u"),
                        {"u": str(legacy.id)})
    delivery = await _delivery(pg_db, blocks=[("memory", str(lane.id))])
    await _delivery(pg_db, blocks=[("memory", str(lane.id))], surface="codex", role="review",
                    session="codex-review", payload_hash="c" * 64)
    now = datetime.now(UTC)
    pg_db.add(UsageSession(provider="claude", session_id="lane-transcript", agent_id="sub-1", first_at=now,
                           last_at=now, launch_mode="subagent:general-purpose", delivery_id=delivery))
    await pg_db.flush()

    queue = await build_queue(pg_db)

    assert [r.key for r in queue.rows] == [f"memory:{lane.id}"]
    row = queue.rows[0]
    assert (row.change, row.actions, row.base_revision, row.version) == ("create", ["create", "update"], None, 2)
    assert (row.scope_before, row.scope_after) == (None, "global reference")
    assert row.through_revision == (await _revisions(pg_db, lane.id))[-1].id
    assert row.after is not None and row.delta_tokens is not None
    assert row.delta_tokens == row.after["tokens"] > 0
    assert row.reach is not None and (row.reach.starts, row.reach.subagent_starts) == (2, 1)
    assert {(r.harness, r.role) for r in row.reach.receivers} == {("claude_code", "implementation"), ("codex", "review")}
    assert row.reach.starts_per_day == 0.4  # (2 starts + 1 subagent) / 7 days
    assert row.tokens_per_day == round(row.delta_tokens * 0.4)
    (writer,) = row.writers
    assert (writer.kind, writer.session, writer.harness, writer.work_role, writer.project) == (
        "agent", "aico-widget-lane", "claude_code", "implementation", "agent-hub")
    assert row.hint is not None and (row.hint.label, row.hint.confidence) == ("looks session-only", 0.93)
    assert queue.summary.count == 1 and queue.summary.global_count == 1


async def test_keep_records_through_the_seen_revision_and_a_later_change_queues_again(pg_db: AsyncSession) -> None:
    memory = await _memory(pg_db, "**Rule**: one.", writer=LANE)
    row = (await build_queue(pg_db)).rows[0]
    _as(OWNER)

    kept = await keep(pg_db, DecideRequest(items=[_item(row)], note="fine"))

    assert kept.results[0].outcome == "recorded"
    review = (await pg_db.execute(select(ContextChangeReview))).scalar_one()
    assert (review.decision, review.through_revision, review.by_kind, review.note) == (
        "keep", row.through_revision, "owner", "fine")
    assert (await build_queue(pg_db)).rows == []

    await _update(pg_db, memory, writer=OTHER_LANE, content="**Rule**: one, reworded.")
    again = (await build_queue(pg_db)).rows
    assert [(r.change, r.base_revision, r.sessions) for r in again] == [
        ("update", row.through_revision, ["aico-widget-other"])]


async def test_refuse_restores_the_revision_before_the_first_unreviewed_change(
    pg_db: AsyncSession, quiet: AsyncMock
) -> None:
    memory = await _memory(pg_db, "**Deploys**: ask first.", writer=OWNER, scope="project", scope_id="agent-hub")
    original = (await _revisions(pg_db, memory.id))[-1]
    await _update(pg_db, memory, writer=LANE, content="**Deploys**: never ask.", scope="global", scope_id=None, tier=1)
    await _update(pg_db, memory, writer=LANE, summary="lane summary")
    row = (await build_queue(pg_db)).rows[0]
    assert (row.change, row.base_revision, row.scope_before, row.scope_after) == (
        "scope", original.id, "project agent-hub reference", "global mandate")
    _as(OWNER)
    quiet.reset_mock()

    result = await refuse(pg_db, DecideRequest(items=[_item(row)]))

    assert result.results[0].outcome == "restored"
    await pg_db.refresh(memory)
    assert (memory.content, memory.scope, memory.scope_id, memory.tier, memory.version) == (
        "**Deploys**: ask first.", "project", "agent-hub", 3, 4)
    quiet.assert_awaited_once_with("**Deploys**: ask first.")  # re-embedded for the restored text
    restore = (await _revisions(pg_db, memory.id))[-1]
    assert (restore.action, restore.writer_kind, restore.id) == ("restore", "owner", result.results[0].result_revision)
    assert (await build_queue(pg_db)).rows == []


async def test_refuse_with_a_newer_unseen_revision_conflicts_and_changes_nothing(pg_db: AsyncSession) -> None:
    memory = await _memory(pg_db, "**Rule**: two.", writer=OWNER)
    await _update(pg_db, memory, writer=LANE, content="**Rule**: two, agent edit.")
    seen = (await build_queue(pg_db)).rows[0]
    await _update(pg_db, memory, writer=OTHER_LANE, content="**Rule**: two, second agent edit.")
    _as(OWNER)

    with pytest.raises(ReviewConflict) as stale:
        await refuse(pg_db, DecideRequest(items=[_item(seen)]))
    assert stale.value.latest_revision == (await _revisions(pg_db, memory.id))[-1].id

    current = (await build_queue(pg_db)).rows[0]
    with pytest.raises(ReviewConflict, match="expected version 2, now 3"):  # memories.version is what was seen
        await refuse(pg_db, DecideRequest(items=[_item(current, expected_version=2)]))
    with pytest.raises(ReviewConflict):
        await rework(pg_db, ReworkRequest(**_item(seen).model_dump(), narrow=Narrow(to="session")))

    await pg_db.refresh(memory)
    assert (memory.content, memory.version, memory.status) == ("**Rule**: two, second agent edit.", 3, "active")
    assert [r.action for r in await _revisions(pg_db, memory.id)] == ["create", "update", "update"]
    assert (await pg_db.execute(select(ContextChangeReview))).scalars().all() == []


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
    assert not task.done(), "expected the refuse to wait on the row lock"
    return task


async def test_refuse_waits_for_an_agent_write_holding_the_row_and_then_conflicts(pg_engine: AsyncEngine) -> None:
    """The version check runs under the row lock: a write the reviewer could not see wins, the refuse changes nothing."""
    async with AsyncSession(pg_engine, expire_on_commit=False) as setup:
        memory = await _memory(setup, "**Rule**: three.", writer=OWNER)
        await _update(setup, memory, writer=LANE, content="**Rule**: three, agent edit.")
        row = (await build_queue(setup)).rows[0]
        await setup.commit()

    async with AsyncSession(pg_engine) as agent, AsyncSession(pg_engine) as owner:
        await _update(agent, memory, writer=OTHER_LANE, content="**Rule**: three, concurrent edit.")  # lock held
        _as(OWNER)
        refusal = await _behind_row_lock(pg_engine, refuse(owner, DecideRequest(items=[_item(row)])))
        await agent.commit()
        with pytest.raises(ReviewConflict, match="expected version 2, now 3"):
            await refusal
        await owner.rollback()

    async with AsyncSession(pg_engine) as check:
        current = await check.get(Memory, memory.id)
        assert current is not None and (current.content, current.version) == ("**Rule**: three, concurrent edit.", 3)
        assert (await check.execute(select(ContextChangeReview))).scalars().all() == []
        assert [r.key for r in (await build_queue(check)).rows] == [f"memory:{memory.id}"]


async def test_session_rows_link_and_a_bulk_refuse_is_all_or_nothing(pg_db: AsyncSession) -> None:
    """A session that created B and deleted A: both rows link; one stale item in the batch undoes nothing."""
    older = await _memory(pg_db, "**Old rule**: kept by the owner.", writer=OWNER)
    created = await _memory(pg_db, "**New rule**: replaces the old one.", writer=LANE)
    _as(LANE)
    assert await MemoryRepository().delete(older.id, db=pg_db)
    await pg_db.flush()
    _as(OWNER)
    await create_prompt(pg_db, slug="lane-prompt", name="Lane prompt", content="Base text.")
    _as(LANE)
    await update_prompt(pg_db, "lane-prompt", content="Lane text.")
    queue = await build_queue(pg_db)
    new_row, old_row = _row(queue, f"memory:{created.id}"), _row(queue, f"memory:{older.id}")
    prompt_row = _row(queue, "prompt:lane-prompt")
    assert old_row.change == "delete" and sorted(new_row.linked) == sorted([old_row.key, prompt_row.key])
    assert [r.key for r in (await build_queue(pg_db, session="aico-widget-lane")).rows] != []

    app = FastAPI()
    from app.api.context_changes import router
    from app.db import get_db

    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: pg_db
    app.dependency_overrides[require_api_key] = lambda: None
    _as(LANE)
    await update_prompt(pg_db, "lane-prompt", content="Lane text, edited again.")  # the reviewer has not seen this
    _as(OWNER)
    body = {"items": [_item(new_row).model_dump(), _item(old_row).model_dump(), _item(prompt_row).model_dump()]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conflict = await client.post("/api/context-observability/changes/refuse", json=body)
        assert conflict.status_code == 409 and conflict.json()["detail"]["key"] == "prompt:lane-prompt"
        await pg_db.refresh(created)
        assert created.status == "active" and await pg_db.get(Memory, older.id) is None  # memory items undone too

        queue = await build_queue(pg_db)
        body = {"items": [_item(_row(queue, k)).model_dump() for k in (new_row.key, old_row.key)]}
        refused = await client.post("/api/context-observability/changes/refuse", json=body)
    assert refused.status_code == 200, refused.text
    outcomes = {r["key"]: r["outcome"] for r in refused.json()["results"]}
    assert outcomes == {new_row.key: "archived", old_row.key: "restored"}
    assert refused.json()["linked_pending"] == ["prompt:lane-prompt"]
    await pg_db.refresh(created)
    restored = await pg_db.get(Memory, older.id)
    assert created.status == "archived" and restored is not None and restored.content == "**Old rule**: kept by the owner."
    assert [r.key for r in (await build_queue(pg_db)).rows] == ["prompt:lane-prompt"]


async def test_rework_narrows_to_the_writers_project_then_a_role_then_session_only(pg_db: AsyncSession) -> None:
    memory = await _memory(pg_db, "**Lane note**: only this repo needs it.", writer=LANE)
    await _delivery(pg_db, blocks=[])  # resolves the lane's project
    row = (await build_queue(pg_db)).rows[0]
    _as(OWNER)

    result = await rework(pg_db, ReworkRequest(**_item(row).model_dump(), narrow=Narrow(to="project")))

    await pg_db.refresh(memory)
    assert result.results[0].outcome == "narrowed"
    assert (memory.scope, memory.scope_id, memory.version) == ("project", "agent-hub", 2)
    assert (await build_queue(pg_db)).rows == []  # the owner's own revision does not queue

    latest = (await _revisions(pg_db, memory.id))[-1]
    assert (latest.action, latest.writer_kind) == ("rework", "owner")
    role = ReworkRequest(target_kind="memory", target_id=str(memory.id), through_revision=latest.id,
                         narrow=Narrow(to="role", role="implementation"), edit=Edit(content="**Lane note**: shorter."))
    await rework(pg_db, role)
    await pg_db.refresh(memory)
    assert memory.applicability["audience_tags"] == ["work-role:implementation"]
    assert (memory.content, memory.scope) == ("**Lane note**: shorter.", "project")

    latest = (await _revisions(pg_db, memory.id))[-1]
    await rework(pg_db, ReworkRequest(target_kind="memory", target_id=str(memory.id), through_revision=latest.id,
                                      narrow=Narrow(to="session")))
    await pg_db.refresh(memory)
    assert memory.status == "archived"
    with pytest.raises(ValueError):
        Narrow(to="role", role="not-a-role")


async def test_prompt_create_is_disabled_and_update_restored_on_refuse(pg_db: AsyncSession) -> None:
    _as(LANE)
    await create_prompt(pg_db, slug="agent-made", name="Agent made", content="Agent text.", is_global=True)
    _as(OWNER)
    await create_prompt(pg_db, slug="owner-made", name="Owner made", content="Owner text.")
    _as(LANE)
    await update_prompt(pg_db, "owner-made", content="Agent rewrite.")
    queue = await build_queue(pg_db)
    created, updated = _row(queue, "prompt:agent-made"), _row(queue, "prompt:owner-made")
    assert (created.change, updated.change) == ("create", "update")
    _as(OWNER)

    result = await refuse(pg_db, DecideRequest(items=[_item(created), _item(updated)]))

    assert {r.key: r.outcome for r in result.results} == {created.key: "disabled", updated.key: "restored"}
    prompts = {p.slug: p for p in (await pg_db.execute(select(Prompt).execution_options(populate_existing=True))).scalars()}
    assert prompts["agent-made"].enabled is False and prompts["owner-made"].content == "Owner text."
    assert (await build_queue(pg_db)).rows == []


async def test_placement_change_refuse_restores_the_layer_and_conflicts_on_unseen_rules(pg_db: AsyncSession) -> None:
    from app.services.runtime_context import (
        RuntimeContextOverridePayload,
        replace_runtime_context_overrides,
    )

    _as(OWNER)
    await create_prompt(pg_db, slug="guard", name="Guard", content="Never expose secrets.", is_global=True)
    _as(LANE)
    await replace_runtime_context_overrides(pg_db, consumer_profile="agent_startup", project_id="agent-hub", overrides=[
        RuntimeContextOverridePayload(source_type="prompt", source_id="guard", mode="exclude")])
    row = _row(await build_queue(pg_db), "placement:agent_startup|agent-hub")
    assert row.change == "placement" and row.before == {"placements": []}
    assert [p["mode"] for p in row.after["placements"]] == ["exclude"]

    pg_db.add(RuntimeContextOverride(consumer_profile="agent_startup", project_id="agent-hub", source_type="prompt",
                                     source_id="guard-2", mode="include", enabled=True, position=50))
    await pg_db.flush()  # a rule written without a change record
    _as(OWNER)
    with pytest.raises(ReviewConflict, match="placement rules changed"):
        await refuse(pg_db, DecideRequest(items=[_item(row)]))
    await pg_db.execute(text("DELETE FROM runtime_context_overrides WHERE source_id = 'guard-2'"))

    result = await refuse(pg_db, DecideRequest(items=[_item(row)]))

    assert result.results[0].outcome == "restored"
    assert (await pg_db.execute(select(RuntimeContextOverride))).scalars().all() == []
    assert (await build_queue(pg_db)).rows == []
