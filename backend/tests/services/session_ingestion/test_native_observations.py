"""Real isolated PostgreSQL proof of the first native multi-source reconciliation seam."""

import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import _get_async_url
from app.models import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    Session,
    SessionEvent,
)
from app.services.session_ingestion.models import TranscriptIngestRequest
from app.services.session_ingestion.native_models import (
    NativeObservation,
    NativeObservationBatch,
    NativeSourceRegistration,
)
from app.services.session_ingestion.native_observations import (
    ingest_native_observations,
    register_native_source,
)
from app.services.session_ingestion.service import (
    SessionIngestionConflict,
    ingest_transcript_events,
)

MIGRATION = Path(__file__).resolve().parents[3] / "alembic/versions/f1a2b3c4d5e6_native_observation_ledger.py"


def _migration():
    spec = importlib.util.spec_from_file_location("native_ledger_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(kind, payload, ordinal=None):
    obj = {"type": kind, "timestamp": "2026-09-30T17:00:00Z", "payload": payload}
    if ordinal is not None:
        obj["ordinal"] = ordinal
    return json.dumps(obj) + "\n"


def _observation(thread, position=1, *, status="completed", item_id="durable-command", quality="durable", origin="stored_snapshot", owner=None, command="printf proof"):
    return NativeObservation(position=position, thread_id=thread, turn_id="turn-proof", item_id=item_id, identity_quality=quality, origin=origin, kind="command_execution", history_owner_thread_id=owner, requested_model="requested-only", configured_model="configured-only", payload={"item": {"type": "commandExecution", "id": item_id, "command": command, "status": status, **({"exitCode": 0} if status == "completed" else {})}})


@pytest.fixture
async def isolated_native_db():
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test", "Native conformance must use only the isolated test database"
    schema = "native_observations_" + uuid4().hex
    owner_engine = create_async_engine(url)

    def install(connection):
        with Operations.context(MigrationContext.configure(connection)) as op:
            op.execute(sa.schema.CreateSchema(schema))
            op.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            # Minimal isolated baseline uses current columns but excludes unrelated FKs.
            # All DDL is executed through the migration fixture.
            for model in (Session, SessionEvent):
                columns = [sa.Column(column.name, column.type, primary_key=column.primary_key, nullable=column.nullable, server_default=column.server_default) for column in model.__table__.columns]
                op.create_table(model.__tablename__, *columns)
            _migration().upgrade()

    async with owner_engine.begin() as connection:
        await connection.run_sync(install)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with owner_engine.begin() as connection:
            def remove(sync):
                with Operations.context(MigrationContext.configure(sync)) as op:
                    op.execute(sa.schema.DropSchema(schema, cascade=True))
            await connection.run_sync(remove)
        await owner_engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_native_receipts_reconcile_rollout_without_duplicate_commands(isolated_native_db, tmp_path):
    factory = isolated_native_db
    thread = str(uuid4())
    path = tmp_path / "native.jsonl"
    path.write_text(_record("session_meta", {"id": thread, "session_id": "root-runtime-alias"}))
    async with factory() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={"transcript_path": str(path)})
        db.add(session)
        await db.commit()
        def registration(kind):
            return NativeSourceRegistration(namespace="fixture-host:fixture-storage", source_kind=kind, producer_id="fixture-owner", epoch="epoch-1", collector_id="fixture", provider_version="fixture", schema_fingerprint="fixture-v1", thread_id=thread, transcript_path=str(path) if kind == "rollout" else None)
        app = await register_native_source(db, session, registration("app_server"))
        rollout = await register_native_source(db, session, registration("rollout"))
        assert app.authenticity == "collector_attested" and rollout.authenticity == "local_verified"
        # Final state arrives over App Server; it creates no competing query events.
        result = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[_observation(thread)]))
        assert result.committed_position == 1
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 0
        path.write_text(path.read_text() + _record("event_msg", {"type": "task_started", "turn_id": "turn-proof"}) + _record("event_msg", {"type": "item_completed", "turn_id": "turn-proof", "started_at_ms": 1790787600000, "completed_at_ms": 1790787600001, "item": {"type": "CommandExecution", "id": "durable-command", "command": ["/bin/bash", "-lc", "printf proof"], "status": "completed", "exit_code": 0, "stdout": "proof", "stderr": ""}}))
        refresh = await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        assert refresh.events_appended == 2
        entities = (await db.execute(sa.select(NativeCommandEntity))).scalars().all()
        receipts = (await db.execute(sa.select(NativeObservationReceipt))).scalars().all()
        assert len(entities) == 1 and len(receipts) == 2
        entity = entities[0]
        assert entity.thread_id == thread and entity.turn_id == "turn-proof"
        assert len(entity.projection_event_ids) == 2 and entity.observed_model is None
        assert session.model == "codex/unknown"
        raw_rollout = next(row.observation for row in receipts if row.source_id == rollout.source_id)
        assert raw_rollout["aliases"] == [{"kind": "transcript_runtime_session_id", "value": "root-runtime-alias"}]
        assert raw_rollout["source_reference"]["record_sha256"]
        checkpoint = refresh.next_checkpoint
        replay = await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path), checkpoint="stale"), session=session)
        assert replay.events_appended == 0 and replay.next_checkpoint == checkpoint
        # Lost acknowledgments reuse the receipt identity; stale acknowledgments cannot rewind.
        repeated = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[_observation(thread)], acknowledged_position=0))
        assert repeated.dispositions[0].disposition == "replayed" and repeated.committed_position == 1
        conflict = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[_observation(thread, command="other")]))
        assert conflict.dispositions[0].issue_code == "receipt_payload_conflict"
        assert (await db.execute(sa.select(NativeCommandEntity))).scalars().one().command["command"] == "printf proof"
        assert len((await db.execute(sa.select(NativeObservationIssue))).scalars().all()) == 1
        # A new lifecycle observation has a new receipt, not a conflicting replay.
        lifecycle = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[_observation(thread, 2, status="running")]))
        assert lifecycle.dispositions[0].disposition == "reconciled"
        assert entity.status == "completed"
        provisional = _observation(thread, 3, item_id="item-1", origin="active_resume_snapshot")
        inherited = _observation(thread, 4, item_id="parent-command", owner="fork-origin")
        final_read = _observation(thread, 5)
        # Missing prefix stays unacknowledged until the missing receipts arrive.
        gap = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[final_read], acknowledged_position=999))
        assert gap.committed_position == 2
        finished = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[provisional, inherited]))
        assert finished.committed_position == 5
        assert [row.issue_code for row in finished.dispositions] == ["provisional_identity", "inherited_history"]
        assert len((await db.execute(sa.select(NativeCommandEntity))).scalars().all()) == 1
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 2
        unsupported = NativeObservation(position=6, thread_id=thread, origin="live", kind="future-provider-kind", payload={"future": {"retained": True}})
        unknown = await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[unsupported]))
        assert unknown.committed_position == 6 and unknown.dispositions[0].issue_code == "unsupported_observation_kind"
        # Later rollout lifecycle records retain provenance without replaying query work.
        original = path.read_text()
        later = json.loads(original.splitlines()[-1])
        later["payload"]["item"]["stdout"] = "additional retained output"
        path.write_text(original + json.dumps(later) + "\n")
        later_refresh = await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        assert later_refresh.events_appended == 0 and later_refresh.events_skipped == 2
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 2
        # Copied fork headers mark command history as inherited, never child work.
        inherited_payload = json.loads(original.splitlines()[-1])["payload"]
        inherited_payload["item"]["id"] = "copied-parent-execution"
        path.write_text(path.read_text() + _record("session_meta", {"id": "fork-origin"}) + _record("event_msg", inherited_payload))
        fork_refresh = await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        assert fork_refresh.events_appended == 0 and fork_refresh.events_skipped == 2
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 2
        assert (await db.execute(sa.select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == rollout.source_id, NativeObservationReceipt.position == 3))).scalars().one().disposition == "inherited"
        # A child sharing its root runtime alias is a different canonical subject.
        child_thread = str(uuid4())
        child = Session(id=child_thread, parent_session_id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={})
        db.add(child)
        await db.commit()
        child_registration = registration("app_server").model_copy(update={"thread_id": child_thread})
        child_source = await register_native_source(db, child, child_registration)
        child_observation = _observation(child_thread).model_copy(update={"aliases": [{"kind": "api_session_id", "value": "root-runtime-alias"}]})
        await ingest_native_observations(db, child, child_source.source_id, NativeObservationBatch(observations=[child_observation]))
        assert len((await db.execute(sa.select(NativeCommandEntity))).scalars().all()) == 2
        assert child.parent_session_id == thread
        # Authorization/binding failures roll back the entire batch, including its prefix.
        with pytest.raises(SessionIngestionConflict):
            await ingest_native_observations(db, session, app.source_id, NativeObservationBatch(observations=[_observation(thread, 7), _observation("another-thread", 8)]))
        await db.rollback()
    async with factory() as verify:
        assert await verify.get(NativeObservationReceipt, (app.source_id, 7)) is None
        assert len((await verify.execute(sa.select(SessionEvent))).scalars().all()) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_receipts_have_one_entity_and_contiguous_server_position(isolated_native_db):
    factory = isolated_native_db
    thread = str(uuid4())
    async with factory() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={})
        db.add(session)
        await db.commit()
        source = await register_native_source(db, session, NativeSourceRegistration(namespace="isolated", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="fixture", provider_version="fixture", schema_fingerprint="v1", thread_id=thread))
    async def ingest(position):
        async with factory() as db:
            session = await db.get(Session, thread)
            return await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(thread, position)]))
    await asyncio.gather(ingest(2), ingest(1), ingest(1))
    async with factory() as db:
        result = await ingest_native_observations(db, await db.get(Session, thread), source.source_id, NativeObservationBatch(acknowledged_position=0))
        assert result.committed_position == 2
        assert len((await db.execute(sa.select(NativeCommandEntity))).scalars().all()) == 1
        assert len((await db.execute(sa.select(NativeObservationReceipt))).scalars().all()) == 2
