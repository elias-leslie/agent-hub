"""Real isolated PostgreSQL proof of the first native multi-source reconciliation seam."""

import asyncio
import importlib.util
import json
import os
import sqlite3
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
from app.services.session_ingestion.app_server_observations import (
    SUPPORTED_VERSION,
    protocol_contract,
)
from app.services.session_ingestion.models import TranscriptIngestRequest
from app.services.session_ingestion.native_models import (
    NativeObservation,
    NativeObservationBatch,
    NativeSourceRegistration,
)
from app.services.session_ingestion.native_observations import (
    ingest_native_observations,
    native_capture_status,
    register_native_source,
)
from app.services.session_ingestion.service import (
    SessionIngestionConflict,
    ingest_transcript_events,
)

MIGRATION = Path(__file__).resolve().parents[3] / "alembic/versions/b46d91c2e7a8_native_observation_ledger.py"


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


def _wire(thread, position, method, params, request_id=None):
    wire = {"method": method, "params": params}
    if request_id is not None:
        wire["id"] = request_id
    return NativeObservation(position=position, thread_id=thread, origin="live", kind="app_server_event", payload=wire)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_managed_wire_commands_approvals_usage_and_gaps_are_durable(isolated_native_db, tmp_path):
    factory = isolated_native_db
    thread = str(uuid4())
    path = tmp_path / "managed.jsonl"
    path.write_text(_record("session_meta", {"id": thread}))
    async with factory() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={"transcript_path": str(path)})
        db.add(session)
        await db.commit()
        reg = NativeSourceRegistration(namespace="managed-fixture", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="summitflow", provider_version=SUPPORTED_VERSION, schema_fingerprint=protocol_contract()[0], thread_id=thread)
        source = await register_native_source(db, session, reg)
        await register_native_source(db, session, reg.model_copy(update={"source_kind": "rollout", "transcript_path": str(path)}))
        command = {"type": "commandExecution", "id": "durable-command", "command": "printf proof", "cwd": str(tmp_path), "commandActions": [], "status": "inProgress"}
        started = _wire(thread, 1, "item/started", {"threadId": thread, "turnId": "turn-proof", "item": command, "startedAtMs": 1})
        request = _wire(thread, 2, "item/commandExecution/requestApproval", {"threadId": thread, "turnId": "turn-proof", "itemId": "durable-command", "startedAtMs": 2, "command": "printf proof"}, 99)
        response = NativeObservation(position=3, thread_id=thread, origin="live", kind="approval_response", payload={"request_id": 99, "response": {"decision": "accept"}}, source_reference={"turn_id": "turn-proof", "item_id": "durable-command"})
        resolved = _wire(thread, 4, "serverRequest/resolved", {"threadId": thread, "requestId": 99})
        completed = _wire(thread, 5, "item/completed", {"threadId": thread, "turnId": "turn-proof", "item": {**command, "status": "completed", "exitCode": 0}, "completedAtMs": 5})
        counts = {"inputTokens": 10, "cachedInputTokens": 2, "outputTokens": 3, "reasoningOutputTokens": 0, "totalTokens": 13}
        usage = _wire(thread, 6, "thread/tokenUsage/updated", {"threadId": thread, "turnId": "turn-proof", "tokenUsage": {"total": counts, "last": counts}})
        interrupted = _wire(thread, 7, "turn/completed", {"threadId": thread, "turn": {"id": "interrupted-turn", "items": [], "status": "interrupted"}})
        compacted = _wire(thread, 8, "item/completed", {"threadId": thread, "turnId": "turn-proof", "item": {"id": "compaction-1", "type": "contextCompaction"}, "completedAtMs": 8})
        # Out-of-order final receipts are durable but cannot acknowledge a gap.
        gap = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[completed, usage, interrupted, compacted], acknowledged_position=999))
        assert gap.committed_position == 0
        health = await native_capture_status(db, session)
        assert next(s for s in health["sources"] if s["source_id"] == source.source_id)["first_missing_position"] == 1
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[started, request, response, resolved]))
        assert result.committed_position == 8
        assert [d.disposition for d in result.dispositions] == ["reconciled", "retained", "retained", "retained"]
        # A lost acknowledgement replays all receipts without token or command work.
        replay = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[started, request, response, resolved, completed, usage, interrupted, compacted]))
        assert all(d.disposition == "replayed" for d in replay.dispositions)
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 0
        receipts = (await db.execute(sa.select(NativeObservationReceipt))).scalars().all()
        assert next(r for r in receipts if r.position == 2).observation == request.model_dump(mode="json")
        assert next(r for r in receipts if r.position == 4).observation == resolved.model_dump(mode="json")
        # Rollout owns the projection. Both sources link to precisely one command.
        path.write_text(path.read_text() + _record("event_msg", {"type": "task_started", "turn_id": "turn-proof"}) + _record("event_msg", {"type": "item_completed", "turn_id": "turn-proof", "started_at_ms": 1, "completed_at_ms": 5, "item": {"type": "CommandExecution", "id": "durable-command", "command": ["/bin/bash", "-lc", "printf proof"], "cwd": str(tmp_path), "status": "completed", "exit_code": 0, "stdout": "proof", "stderr": ""}}))
        await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        entity = (await db.execute(sa.select(NativeCommandEntity))).scalars().one()
        assert entity.status == "completed" and entity.observed_model is None
        assert len(entity.projection_event_ids) == 2
        assert len((await db.execute(sa.select(SessionEvent))).scalars().all()) == 2
        # Unsupported shapes retain their exact raw payload and an explicit issue.
        invalid = _wire(thread, 9, "item/completed", {"threadId": thread, "turnId": "turn-proof", "item": {"type": "future", "id": "future"}})
        invalid_result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[invalid]))
        assert invalid_result.dispositions[0].issue_code == "unsupported_app_server_shape"
        row = await db.get(NativeObservationReceipt, (source.source_id, 9))
        assert row.observation == invalid.model_dump(mode="json")
        # Envelope identity cannot move a sibling/parent wire subject to this child.
        foreign = _wire(thread, 10, "turn/completed", {"threadId": "sibling", "turn": {"id": "foreign", "items": [], "status": "completed"}})
        foreign_result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[foreign]))
        assert foreign_result.dispositions[0].issue_code == "app_server_thread_mismatch"
        bad_approval = response.model_copy(update={"position": 11, "source_reference": {"turn_id": "sibling-turn", "item_id": "durable-command"}})
        bad_result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[bad_approval]))
        assert bad_result.dispositions[0].issue_code == "approval_subject_mismatch"
        different_connection = response.model_copy(update={"position": 12, "source_reference": {"connection_id": "restarted", "turn_id": "turn-proof", "item_id": "durable-command"}})
        missing_result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[different_connection]))
        assert missing_result.dispositions[0].issue_code == "approval_request_unavailable"
        different_id_type = _wire(thread, 13, "serverRequest/resolved", {"threadId": thread, "requestId": "99"})
        missing_result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[different_id_type]))
        assert missing_result.dispositions[0].issue_code == "approval_request_unavailable"
        private_health = NativeObservation(position=14, thread_id=thread, origin="live", kind="capture_health", payload={"state": "capture_gap", "capture_gaps": 1, "transport": "stdio", "approval_contents": "private-health-fixture"})
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[private_health]))
        public_health = await native_capture_status(db, session)
        assert "private-health-fixture" not in json.dumps(public_health)
        assert next(s for s in public_health["sources"] if s["source_id"] == source.source_id)["capture_health"] == {"state": "capture_gap", "capture_gaps": 1, "transport": "stdio"}
        assert session.model == "codex/unknown"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unsupported_version_is_visible_without_corrupting_entity(isolated_native_db):
    factory = isolated_native_db
    thread = str(uuid4())
    async with factory() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={})
        db.add(session)
        await db.commit()
        reg = NativeSourceRegistration(namespace="fixture", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="fixture", provider_version="unsupported", schema_fingerprint="unknown", thread_id=thread)
        source = await register_native_source(db, session, reg)
        raw = _wire(thread, 1, "turn/completed", {"threadId": thread, "turn": {"id": "turn", "items": [], "status": "completed"}})
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[raw]))
        assert result.committed_position == 1
        assert result.dispositions[0].issue_code == "unsupported_app_server_contract"
        assert not (await db.execute(sa.select(NativeCommandEntity))).scalars().all()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("registration_order", ["before_ingestion", "after_ingestion"])
async def test_installed_app_server_canary_reconciles_real_rollouts(isolated_native_db, registration_order):
    """Optional runtime-to-PostgreSQL proof using the private toy-only canary export."""
    evidence_path = os.environ.get("ARCHITECTURE_D_CANARY_EVIDENCE")
    if not evidence_path:
        pytest.skip("Run the isolated installed App Server canary and supply its private evidence directory")
    evidence = Path(evidence_path).resolve()
    assert evidence.is_relative_to(Path("/tmp")) and evidence.stat().st_uid == os.getuid()
    assert evidence.stat().st_mode & 0o077 == 0
    from app.services.session_ingestion.adapters.transcript_parsers import (
        transcript_session_metadata,
    )

    with sqlite3.connect(f"file:{evidence / 'outbox.sqlite'}?mode=ro", uri=True) as capture:
        capture.row_factory = sqlite3.Row
        threads = [dict(row) for row in capture.execute("SELECT * FROM threads ORDER BY id")]
        observations = {thread["id"]: [NativeObservation.model_validate(json.loads(row[0])) for row in capture.execute("SELECT observation FROM events WHERE thread=? ORDER BY position", (thread["id"],))] for thread in threads}
    paths = {}
    headers = {}
    for path in (evidence / "sessions").rglob("*.jsonl"):
        header = transcript_session_metadata(str(path))
        if header:
            paths[header["id"]] = path
            headers[header["id"]] = header
    assert len(threads) >= 3, "Canary must include own thread, fork and native child"
    source_ids = {}
    async with isolated_native_db() as db:
        for thread in threads:
            header = headers[thread["id"]]
            source = header.get("source", {})
            subagent = source.get("subagent", {}) if isinstance(source, dict) else {}
            parent = header.get("parent_thread_id") or subagent.get("thread_spawn", {}).get("parent_thread_id")
            session = Session(id=thread["id"], project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", parent_session_id=parent, provider_metadata={"transcript_path": str(paths[thread["id"]])})
            db.add(session)
        await db.commit()
        for thread in threads:
            session = await db.get(Session, thread["id"])
            if registration_order == "after_ingestion":
                await ingest_transcript_events(db, thread["id"], TranscriptIngestRequest(provider="codex", transcript_path=str(paths[thread["id"]])), session=session)
            registration = NativeSourceRegistration.model_validate(json.loads(thread["registration"]))
            app_source = await register_native_source(db, session, registration)
            rollout_source = await register_native_source(db, session, registration.model_copy(update={"source_kind": "rollout", "producer_id": "canary-rollout", "epoch": "rollout", "transcript_path": str(paths[thread["id"]]), "reconcile_existing_rollout": True}))
            source_ids[thread["id"]] = (app_source.source_id, rollout_source.source_id)
            result = await ingest_native_observations(db, session, app_source.source_id, NativeObservationBatch(observations=observations[thread["id"]]))
            assert result.committed_position == len(observations[thread["id"]])
            assert not [d.issue_code for d in result.dispositions if d.disposition == "unsupported"], "Pinned installed notifications must normalize or be explicit retained evidence"
            await ingest_transcript_events(db, thread["id"], TranscriptIngestRequest(provider="codex", transcript_path=str(paths[thread["id"]])), session=session)
            replay = await ingest_native_observations(db, session, app_source.source_id, NativeObservationBatch(observations=observations[thread["id"]], acknowledged_position=0))
            assert all(d.disposition == "replayed" for d in replay.dispositions)
            assert session.model == "codex/unknown"
        entities = (await db.execute(sa.select(NativeCommandEntity))).scalars().all()
        completed = [entity for entity in entities if entity.status == "completed"]
        assert len(completed) == 1, "Exactly one command completed in the canary; fork copies cannot create child work"
        command = completed[0]
        linked = (await db.execute(sa.select(NativeObservationReceipt).where(NativeObservationReceipt.entity_id == command.id))).scalars().all()
        assert {r.source_id for r in linked} == set(source_ids[command.thread_id])
        assert len(command.projection_event_ids) == 2, [(row.event_type, row.call_id) for row in (await db.execute(sa.select(SessionEvent).where(SessionEvent.session_id == command.thread_id))).scalars().all()]
        assert all(entity.observed_model is None for entity in entities)
        issues = (await db.execute(sa.select(NativeObservationIssue))).scalars().all()
        assert not [i.code for i in issues if "conflict" in i.code]
        before = (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one()
        for thread in threads:
            await ingest_transcript_events(db, thread["id"], TranscriptIngestRequest(provider="codex", transcript_path=str(paths[thread["id"]]), checkpoint="stale"), session=await db.get(Session, thread["id"]))
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == before
