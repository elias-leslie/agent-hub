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


def _observation(thread, position=1, *, status="completed", item_id="durable-command", quality="durable", origin="live", owner=None, command="printf proof"):
    native_status = "inProgress" if status == "running" else status
    return NativeObservation(position=position, thread_id=thread, turn_id="turn-proof", item_id=item_id, identity_quality=quality, origin=origin, kind="app_server_event", history_owner_thread_id=owner, requested_model="requested-only", configured_model="configured-only", payload={"method": "item/started" if status == "running" else "item/completed", "params": {"threadId": thread, "turnId": "turn-proof", "startedAtMs": 1, "completedAtMs": 2, "item": {"type": "commandExecution", "id": item_id, "command": command, "cwd": "/tmp", "commandActions": [], "status": native_status, **({"exitCode": 0} if status == "completed" else {})}}})


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
                constraints = [sa.UniqueConstraint("session_id", "turn", "sequence", name="uq_isolated_session_position")] if model is SessionEvent else []
                op.create_table(model.__tablename__, *columns, *constraints)
            _migration().upgrade()
            spec = importlib.util.spec_from_file_location("native_generation_migration", MIGRATION.with_name("c58e42d7a901_native_source_generations.py"))
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()

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
            return NativeSourceRegistration(namespace="fixture-host:fixture-storage", source_kind=kind, producer_id="fixture-owner", epoch="epoch-1", collector_id="fixture", provider_version=SUPPORTED_VERSION, schema_fingerprint=protocol_contract()[0], thread_id=thread, transcript_path=str(path) if kind == "rollout" else None)
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
        source = await register_native_source(db, session, NativeSourceRegistration(namespace="isolated", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="fixture", provider_version=SUPPORTED_VERSION, schema_fingerprint=protocol_contract()[0], thread_id=thread))
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
        usage_receipt = next(r for r in receipts if r.position == 6)
        assert usage_receipt.normalized["accounting"] == "cumulative_snapshot"
        assert usage_receipt.normalized["billing_authority"] is False
        assert usage_receipt.normalized["usage"]["total"] == counts
        assert next(r for r in receipts if r.position == 4).normalized["approval_state"] == "request_cleared"
        assert next(r for r in receipts if r.position == 3).normalized["approval_state"] == "client_responded"
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_profiles_successor_generation_and_legacy_replay(isolated_native_db):
    from app.services.session_ingestion.native_observations import native_evidence_summary

    thread = str(uuid4())
    async with isolated_native_db() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={})
        db.add(session)
        await db.commit()
        registration = NativeSourceRegistration(namespace="isolated", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="fixture", provider_version="codex-cli 0.159.2", schema_fingerprint=protocol_contract("codex-cli 0.159.2")[0], thread_id=thread)
        old = await register_native_source(db, session, registration)
        from app.models import NativeObservationSource
        old_row = await db.get(NativeObservationSource, old.source_id)
        old_row.registration = {key: value for key, value in old_row.registration.items() if key not in {"generation", "predecessor_source_id"}}
        await db.commit()
        assert (await register_native_source(db, session, registration)).source_id == old.source_id
        observation = _wire(thread, 1, "turn/started", {"threadId": thread, "turn": {"id": "turn-old", "items": [], "status": "inProgress"}})
        first = await ingest_native_observations(db, session, old.source_id, NativeObservationBatch(observations=[observation]))
        assert first.dispositions[0].disposition == "retained"
        updated = registration.model_copy(update={"generation": 1, "predecessor_source_id": old.source_id, "provider_version": SUPPORTED_VERSION, "schema_fingerprint": protocol_contract()[0]})
        new = await register_native_source(db, session, updated)
        assert new.source_id != old.source_id and new.committed_position == 0
        await ingest_native_observations(db, session, new.source_id, NativeObservationBatch(observations=[observation]))
        replay = await ingest_native_observations(db, session, old.source_id, NativeObservationBatch(observations=[observation]))
        assert replay.dispositions[0].disposition == "replayed"
        health = await native_capture_status(db, session)
        assert {row["generation"] for row in health["sources"]} == {0, 1}
        assert all(row["protocol_supported"] and row["freshness"] == "recent" for row in health["sources"])
        assert (await native_evidence_summary(db, session))["commands"] == []
        with pytest.raises(SessionIngestionConflict, match="preceding source"):
            await register_native_source(db, session, updated.model_copy(update={"generation": 3}))
        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unbound_receipts_have_no_fabricated_session_and_exact_atomic_ack(isolated_native_db):
    from app.models import NativeObservationSource
    from app.services.session_ingestion.native_models import (
        NativeQuarantineBatch,
        NativeQuarantineObservation,
        NativeQuarantineRegistration,
    )
    from app.services.session_ingestion.native_observations import (
        ingest_native_quarantine,
        register_native_quarantine,
    )

    async with isolated_native_db() as db:
        registration = NativeQuarantineRegistration(project_id="agent-hub", namespace="isolated", producer_id="producer", epoch="epoch", collector_id="collector", provider_version=SUPPORTED_VERSION, schema_fingerprint=protocol_contract()[0])
        with pytest.raises(ValueError):
            await register_native_quarantine(db, registration.model_copy(update={"project_id": "unregistered-project"}))
        receipt = await register_native_quarantine(db, registration)
        source = await db.get(NativeObservationSource, receipt.source_id)
        assert source.session_id is None and source.project_id == "agent-hub"
        raw = NativeQuarantineObservation(position=2, payload={"method": "unknown", "params": {"private": "retained"}}, source_reference={"connection_id": "owned-connection"})
        missing = await ingest_native_quarantine(db, source, NativeQuarantineBatch(observations=[raw], acknowledged_position=999))
        assert missing.committed_position == 0 and missing.dispositions[0].disposition == "quarantined"
        completed = await ingest_native_quarantine(db, source, NativeQuarantineBatch(observations=[raw.model_copy(update={"position": 1})]))
        assert completed.committed_position == 2
        replay = await ingest_native_quarantine(db, source, NativeQuarantineBatch(observations=[raw]))
        assert replay.dispositions[0].disposition == "replayed"
        conflict = await ingest_native_quarantine(db, source, NativeQuarantineBatch(observations=[raw.model_copy(update={"payload": {"changed": True}})]))
        assert conflict.dispositions[0].disposition == "conflict"
        assert (await db.get(NativeObservationReceipt, (source.id, 2))).observation == raw.model_dump(mode="json")
        assert (await db.execute(sa.select(sa.func.count()).select_from(Session))).scalar_one() == 0
        assert (await db.execute(sa.select(sa.func.count()).select_from(NativeCommandEntity))).scalar_one() == 0
        assert (await db.execute(sa.select(NativeObservationIssue).where(NativeObservationIssue.code == "receipt_payload_conflict"))).scalar_one().observation["payload"] == {"changed": True}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rollout_rewrite_rotates_receipt_generation_and_keeps_projection(isolated_native_db, tmp_path):
    from app.models import NativeObservationSource

    thread = str(uuid4())
    path = tmp_path / "rewrite.jsonl"
    header = _record("session_meta", {"id": thread})
    command = _record("event_msg", {"type": "item_completed", "turn_id": "turn-proof", "started_at_ms": 1, "completed_at_ms": 2, "item": {"type": "CommandExecution", "id": "durable-command", "command": ["/bin/bash", "-lc", "printf proof"], "status": "completed", "exit_code": 0, "stdout": "proof", "stderr": ""}})
    path.write_text(header + command)
    async with isolated_native_db() as db:
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={"transcript_path": str(path)})
        db.add(session)
        await db.commit()
        old = await register_native_source(db, session, NativeSourceRegistration(namespace="rewrite", source_kind="rollout", producer_id="owner", epoch="epoch", collector_id="fixture", provider_version="fixture", schema_fingerprint="fixture", thread_id=thread, transcript_path=str(path), reconcile_existing_rollout=True))
        await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 2
        # Same inode, different byte layout: the execution identity remains exact.
        path.write_text(header + _record("event_msg", {"type": "task_started", "turn_id": "turn-proof"}) + command)
        await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        sources = (await db.execute(sa.select(NativeObservationSource))).scalars().all()
        assert len(sources) == 2
        successor = next(row for row in sources if row.id != old.source_id)
        assert successor.registration["_parser_predecessor_source_id"] == old.source_id
        assert successor.registration["_parser_generation"] == 1 and successor.committed_position == 1
        original_source = await db.get(NativeObservationSource, old.source_id)
        update = NativeSourceRegistration.model_validate({key: value for key, value in original_source.registration.items() if not key.startswith("_")}).model_copy(update={"generation": 1, "predecessor_source_id": old.source_id, "provider_version": "fixture-updated"})
        upgraded = await register_native_source(db, session, update)
        assert upgraded.source_id not in {old.source_id, successor.id}
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 2
        assert (await db.execute(sa.select(sa.func.count()).select_from(NativeCommandEntity))).scalar_one() == 1
        assert not (await db.execute(sa.select(NativeObservationIssue).where(NativeObservationIssue.code.like("%conflict%")))).scalars().all()


def test_native_identity_comes_from_validated_wire_origin_not_id_spelling():
    from app.services.session_ingestion.app_server_observations import interpret_wire

    registration = {"provider_version": SUPPORTED_VERSION, "schema_fingerprint": protocol_contract()[0]}
    for item_id in ("item-1", "durable-command"):
        wire = _wire("own-thread", 1, "item/started", {"threadId": "own-thread", "turnId": "own-turn", "item": {"type": "commandExecution", "id": item_id, "command": "printf proof", "cwd": "/tmp", "commandActions": [], "status": "inProgress"}, "startedAtMs": 1})
        live, issue = interpret_wire(wire, registration)
        assert issue is None and live.identity_quality == "durable"
        snapshot, issue = interpret_wire(wire.model_copy(update={"origin": "active_resume_snapshot", "identity_quality": "durable"}), registration)
        assert issue is None and snapshot.identity_quality == "provisional"


async def _managed_fixture(db, tmp_path):
    from app.services.session_ingestion.canonical_projection import (
        ACCEPTANCE_CHECKS,
        record_projection_acceptance,
        set_projection_mode,
    )
    thread = str(uuid4())
    path = tmp_path / (thread + ".jsonl")
    path.write_text(_record("session_meta", {"id": thread}))
    session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={"transcript_path": str(path)})
    db.add(session)
    await db.commit()
    registration = NativeSourceRegistration(namespace="canonical-fixture", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="summitflow/codex-managed", provider_version=SUPPORTED_VERSION, schema_fingerprint=protocol_contract()[0], thread_id=thread)
    source = await register_native_source(db, session, registration)
    await register_native_source(db, session, registration.model_copy(update={"source_kind": "rollout", "transcript_path": str(path)}))
    with pytest.raises(SessionIngestionConflict, match="Server-owned acceptance"):
        await set_projection_mode(db, session, "canonical_managed")
    await db.rollback()
    session = await db.get(Session, thread)
    await record_projection_acceptance(db, session, {"evidence_sha256": "a" * 64, "checks": {key: True for key in ACCEPTANCE_CHECKS}})
    await set_projection_mode(db, session, "canonical_managed")
    return session, source, path


def _rollout_command(thread, *, user=True):
    return (_record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "fixture prompt"}]}) if user else "") + _record("event_msg", {"type": "item_completed", "turn_id": "turn-proof", "started_at_ms": 1, "completed_at_ms": 2, "item": {"type": "CommandExecution", "id": "durable-command", "command": ["/bin/bash", "-lc", "printf proof"], "cwd": "/tmp", "status": "completed", "exit_code": 0, "stdout": "proof", "stderr": ""}})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_canonical_live_first_uses_partial_pair_and_atomic_legacy_relocation(isolated_native_db, tmp_path):
    from app.services.session_ingestion.canonical_projection import set_projection_mode
    async with isolated_native_db() as db:
        session, source, path = await _managed_fixture(db, tmp_path)
        started = _observation(session.id, status="running")
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[started]))
        rows = (await db.execute(sa.select(SessionEvent))).scalars().all()
        assert len(rows) == 1 and rows[0].event_type == "tool_use"
        assert rows[0].tool_input["ordering"] == "provisional" and rows[0].tool_input["native_turn_id"] == "turn-proof"
        original_use = str(rows[0].id)
        final = _observation(session.id, 2)
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[final]))
        entity = (await db.execute(sa.select(NativeCommandEntity))).scalar_one()
        original_pair = list(entity.projection_event_ids)
        assert len(original_pair) == 2 and original_use in original_pair
        path.write_text(path.read_text() + _rollout_command(session.id))
        await ingest_transcript_events(db, session.id, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        rows = (await db.execute(sa.select(SessionEvent).order_by(SessionEvent.turn, SessionEvent.sequence))).scalars().all()
        assert [(row.event_type, row.turn, row.sequence) for row in rows] == [("user_message", 1, 1), ("tool_use", 1, 2), ("tool_result", 1, 3)]
        assert entity.projection_event_ids == original_pair
        assert all(not row.source_event_id.startswith("native-command:") for row in rows)
        assert all(row.tool_input is None or "ordering" not in row.tool_input for row in rows)
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[started, final]))
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 3
        rollback = await set_projection_mode(db, session, "shadow")
        assert rollback["projection_authority"] == "rollout"
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(session.id, 3, item_id="after-rollback")]))
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_canonical_partial_live_pair_gets_result_from_rollout_without_duplicate(isolated_native_db, tmp_path):
    async with isolated_native_db() as db:
        session, source, path = await _managed_fixture(db, tmp_path)
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(session.id, status="running")]))
        entity = (await db.execute(sa.select(NativeCommandEntity))).scalar_one()
        use_id = entity.projection_event_ids[0]
        path.write_text(path.read_text() + _rollout_command(session.id))
        await ingest_transcript_events(db, session.id, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        assert len(entity.projection_event_ids) == 2 and use_id in entity.projection_event_ids
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 3
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(session.id, 2)]))
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_canonical_concurrent_live_rollout_and_duplicate_have_one_projection(isolated_native_db, tmp_path):
    async with isolated_native_db() as db:
        session, source, path = await _managed_fixture(db, tmp_path)
        thread = session.id
    path.write_text(path.read_text() + _rollout_command(thread))
    async def live():
        async with isolated_native_db() as db:
            return await ingest_native_observations(db, await db.get(Session, thread), source.source_id, NativeObservationBatch(observations=[_observation(thread)]))
    async def rollout():
        async with isolated_native_db() as db:
            return await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=await db.get(Session, thread))
    await asyncio.gather(live(), rollout(), live())
    async with isolated_native_db() as db:
        entity = (await db.execute(sa.select(NativeCommandEntity))).scalar_one()
        rows = (await db.execute(sa.select(SessionEvent))).scalars().all()
        assert len(rows) == 3 and len(entity.projection_event_ids) == 2
        assert {(row.turn, row.sequence) for row in rows} == {(1, 1), (1, 2), (1, 3)}
        assert (await db.execute(sa.select(sa.func.count()).select_from(NativeObservationReceipt))).scalar_one() == 2


def _snapshot(thread, position, method, item_id, client_id, *, turn="turn-proof", forked_from=None):
    return NativeObservation(position=position, thread_id=thread, origin="active_resume_snapshot" if method == "thread/resume" else "stored_snapshot", kind="app_server_snapshot", payload={"method": method, "thread": {"id": thread, "cliVersion": "0.159.3", "createdAt": 0, "updatedAt": 0, "cwd": "/tmp", "ephemeral": False, "modelProvider": "fixture", "preview": "", "projectId": None, "sessionId": thread, "source": "cli", "status": {"type": "idle"}, "forkedFromId": forked_from, "turns": [{"id": turn, "status": "completed", "items": [{"type": "userMessage", "id": item_id, "clientId": client_id, "content": []}]}]}})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explicit_snapshot_client_id_aliases_are_scoped_and_do_not_replay_history(isolated_native_db, tmp_path):
    from app.models import NativeUserIdentity
    fixture = json.loads((Path(__file__).parents[2] / "fixtures/native_identity_alias_01593.json").read_text())
    async with isolated_native_db() as db:
        session, source, _ = await _managed_fixture(db, tmp_path)
        durable = fixture["active_user_items"][0]["id"]
        provisional = fixture["resumed_user_items"][0]["id"]
        client = fixture["client_user_message_id"]
        observations = [_snapshot(session.id, 1, "thread/read", durable, client), _snapshot(session.id, 2, "thread/resume", provisional, client), _snapshot(session.id, 3, "thread/read", durable, client)]
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=observations))
        assert all(row.disposition == "retained" for row in result.dispositions)
        identity = (await db.execute(sa.select(NativeUserIdentity))).scalar_one()
        assert identity.durable_item_id == durable and {alias["item_id"] for alias in identity.aliases} == {durable, provisional}
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 0
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_snapshot(session.id, 4, "thread/read", durable, client)]))
        assert len(identity.aliases) == 2
        conflict = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_snapshot(session.id, 5, "thread/read", "different-provider-id", client)]))
        assert conflict.dispositions[0].issue_code == "native_user_identity_conflict" and identity.durable_item_id == durable
        missing = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_snapshot(session.id, 6, "thread/resume", provisional, None)]))
        assert missing.dispositions[0].disposition == "unresolved"
        invalid = _snapshot(session.id, 7, "thread/read", durable, client).model_copy(update={"payload": {"method": "thread/read", "thread": {"id": session.id}}})
        assert (await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[invalid]))).dispositions[0].issue_code == "unsupported_snapshot_shape"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_protocol_qualification_needs_full_canary_and_preserves_first_receipt(isolated_native_db):
    from app.services.session_ingestion.native_models import NativeProtocolProfileRegistration
    from app.services.session_ingestion.native_observations import (
        REQUIRED_CANARY_CASES,
        qualify_native_protocol_profile,
    )
    async with isolated_native_db() as db:
        canary = {"version": "codex-cli 0.159.4", "schema_fingerprint": protocol_contract()[0], "external_network": "absent", "provider": "scripted_loopback_fixture", "provider_requests": 1, "cases": {key: True for key in REQUIRED_CANARY_CASES}}
        request = NativeProtocolProfileRegistration(provider_version=canary["version"], schema_fingerprint=canary["schema_fingerprint"], canary_receipt=canary)
        approved = await qualify_native_protocol_profile(db, request)
        fresh = await qualify_native_protocol_profile(db, request.model_copy(update={"canary_receipt": {**canary, "provider_requests": 2}}))
        assert approved["canary_sha256"] == fresh["canary_sha256"]
        with pytest.raises(SessionIngestionConflict):
            await qualify_native_protocol_profile(db, request.model_copy(update={"canary_receipt": {**canary, "external_network": "present"}}))
        await db.rollback()
        thread = str(uuid4())
        session = Session(id=thread, project_id="agent-hub", provider="codex", model="codex/unknown", status="active", session_type="agent", provider_metadata={})
        db.add(session)
        await db.commit()
        source = await register_native_source(db, session, NativeSourceRegistration(namespace="qualified", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="summitflow/codex-managed", provider_version=canary["version"], schema_fingerprint=canary["schema_fingerprint"], thread_id=thread))
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(thread)]))
        assert result.dispositions[0].disposition == "accounted"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_strict_wire_and_terminal_output_conflicts_preserve_canonical_output(isolated_native_db, tmp_path):
    async with isolated_native_db() as db:
        session, source, _ = await _managed_fixture(db, tmp_path)
        direct = NativeObservation(position=1, thread_id=session.id, turn_id="turn-proof", item_id="claim", origin="live", identity_quality="durable", kind="command_execution", payload={"item": {"type": "commandExecution", "id": "claim", "command": "printf fake", "status": "completed"}})
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[direct]))
        assert result.dispositions[0].issue_code == "unverified_app_server_evidence"
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 0
        first = _observation(session.id, 2)
        first.payload["params"]["item"]["aggregatedOutput"] = "first terminal output"
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[first]))
        changed = _observation(session.id, 3)
        changed.payload["params"]["item"]["aggregatedOutput"] = "alternate output"
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[changed]))
        assert result.dispositions[0].issue_code == "entity_terminal_output_conflict"
        output = (await db.execute(sa.select(SessionEvent).where(SessionEvent.event_type == "tool_result"))).scalar_one().tool_output
        assert output["output"] == "first terminal output"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fork_user_aliases_require_owned_live_turn_and_isolate_same_client_id(isolated_native_db, tmp_path):
    from app.models import NativeUserIdentity
    async with isolated_native_db() as db:
        parent, source, _ = await _managed_fixture(db, tmp_path)
        await ingest_native_observations(db, parent, source.source_id, NativeObservationBatch(observations=[_snapshot(parent.id, 1, "thread/read", "parent-user", "shared-client", turn="parent-turn")]))
        parent_id = parent.id
        child, child_source, _ = await _managed_fixture(db, tmp_path)
        copied = _snapshot(child.id, 1, "thread/read", "parent-user", "shared-client", turn="parent-turn", forked_from=parent_id)
        inherited = await ingest_native_observations(db, child, child_source.source_id, NativeObservationBatch(observations=[copied]))
        assert inherited.dispositions[0].disposition == "inherited"
        user = _wire(child.id, 2, "item/started", {"threadId": child.id, "turnId": "child-turn", "startedAtMs": 1, "item": {"type": "userMessage", "id": "child-user", "clientId": "shared-client", "content": []}})
        await ingest_native_observations(db, child, child_source.source_id, NativeObservationBatch(observations=[user]))
        own = _snapshot(child.id, 3, "thread/resume", "item-1", "shared-client", turn="child-turn", forked_from=parent_id)
        retained = await ingest_native_observations(db, child, child_source.source_id, NativeObservationBatch(observations=[own]))
        assert retained.dispositions[0].disposition == "retained"
        identities = (await db.execute(sa.select(NativeUserIdentity))).scalars().all()
        assert len(identities) == 2 and {identity.thread_id for identity in identities} == {parent_id, child.id}
        assert next(identity for identity in identities if identity.thread_id == child.id).durable_item_id == "child-user"
        assert (await db.execute(sa.select(sa.func.count()).select_from(SessionEvent))).scalar_one() == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_raw_retention_preserves_late_approval_binding_replay_and_summary(isolated_native_db, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.services.session_ingestion.native_observations import native_evidence_summary
    from app.services.session_ingestion.native_operator import prune_raw_evidence
    async with isolated_native_db() as db:
        session, source, _ = await _managed_fixture(db, tmp_path)
        request = _wire(session.id, 1, "item/commandExecution/requestApproval", {"threadId": session.id, "turnId": "turn-proof", "itemId": "durable-command", "startedAtMs": 1, "command": "printf proof"}, 42)
        request.source_reference["connection_id"] = "connection"
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[request]))
        receipt = await db.get(NativeObservationReceipt, (source.source_id, 1))
        original_hash = receipt.payload_hash
        receipt.received_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
        cutoff = datetime.now(UTC) - timedelta(days=1)
        preview = await prune_raw_evidence(db, "agent-hub", cutoff)
        assert preview["eligible"] == 1 and preview["pruned"] == 0
        pruned = await prune_raw_evidence(db, "agent-hub", cutoff, apply=True)
        assert pruned["pruned"] == 1 and receipt.payload_hash == original_hash
        assert receipt.observation["payload"] == {"raw_pruned": True}
        assert receipt.normalized["approval_request"]["request_id"] == 42
        before = await native_evidence_summary(db, session)
        assert before["approvals"]["validated_requests"] == 1
        response = NativeObservation(position=2, thread_id=session.id, origin="live", kind="approval_response", payload={"request_id": 42, "response": {"decision": "accept"}}, source_reference={"connection_id": "connection", "turn_id": "turn-proof", "item_id": "durable-command"})
        resolved = _wire(session.id, 3, "serverRequest/resolved", {"threadId": session.id, "requestId": 42})
        resolved.source_reference["connection_id"] = "connection"
        result = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[response, resolved]))
        assert all(disposition.disposition == "retained" for disposition in result.dispositions)
        replay = await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[request]))
        assert replay.dispositions[0].disposition == "replayed"
        summary = await native_evidence_summary(db, session)
        assert summary["approvals"] == {"validated_requests": 1, "bound_responses": 1, "cleared_requests": 1, "unresolved": 0}
        # Distinct exact typed request IDs cannot collapse in the audit projection.
        other = request.model_copy(deep=True, update={"position": 4})
        other.payload["id"] = "42"
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[other]))
        requests = (await db.execute(sa.select(SessionEvent).where(SessionEvent.event_type == "native_approval", SessionEvent.tool_input["kind"].as_string() == "approval_request"))).scalars().all()
        assert len(requests) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_relocation_receipt_and_rollout_checkpoint_rollback_together(isolated_native_db, tmp_path, monkeypatch):
    import app.services.session_ingestion.service as service
    async with isolated_native_db() as db:
        session, source, path = await _managed_fixture(db, tmp_path)
        thread = session.id
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(thread)]))
        before = [(str(row.id), row.turn, row.sequence, row.source_event_id) for row in (await db.execute(sa.select(SessionEvent))).scalars().all()]
        path.write_text(path.read_text() + _rollout_command(thread))
        original = service.append_normalized_events
        async def fail_after_append(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("isolated transaction failure")
        monkeypatch.setattr(service, "append_normalized_events", fail_after_append)
        with pytest.raises(RuntimeError, match="isolated transaction failure"):
            await ingest_transcript_events(db, thread, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        await db.rollback()
    async with isolated_native_db() as verify:
        rows = [(str(row.id), row.turn, row.sequence, row.source_event_id) for row in (await verify.execute(sa.select(SessionEvent))).scalars().all()]
        assert rows == before
        assert (await verify.execute(sa.select(sa.func.count()).select_from(NativeObservationReceipt))).scalar_one() == 1
        restored = await verify.get(Session, thread)
        assert not restored.provider_metadata.get("transcript_ingestion")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owner_acceptance_requires_current_gate_and_matching_actual_ledger(isolated_native_db, tmp_path):
    from app.services.session_ingestion.native_observations import REQUIRED_CANARY_CASES
    from app.services.session_ingestion.native_operator import verify_acceptance
    async with isolated_native_db() as db:
        session, source, path = await _managed_fixture(db, tmp_path)
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_observation(session.id)]))
        path.write_text(path.read_text() + _rollout_command(session.id))
        await ingest_transcript_events(db, session.id, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
        await ingest_native_observations(db, session, source.source_id, NativeObservationBatch(observations=[_snapshot(session.id, 2, "thread/read", "durable-user", "explicit-client"), _snapshot(session.id, 3, "thread/resume", "item-1", "explicit-client")]))
        identity = json.loads((Path(__file__).parents[2] / "fixtures/native_identity_alias_01593.json").read_text())
        canary = {"version": SUPPORTED_VERSION, "schema_fingerprint": protocol_contract()[0], "external_network": "absent", "provider": "scripted_loopback_fixture", "provider_requests": 1, "cases": {key: True for key in REQUIRED_CANARY_CASES}}
        gate = {"schema_version": 1, "kind": "local_full_acceptance", "state": "success", "acceptance_id": "current-acceptance", "source": {"commit": "current", "tree": "current-tree"}}
        with pytest.raises(ValueError, match="current canonical ST"):
            await verify_acceptance(db, session, canary, identity, {**gate, "acceptance_id": "old"}, gate)
        result = await verify_acceptance(db, session, canary, identity, gate, gate)
        assert result["acceptance_recorded"] is True and len(result["evidence_sha256"]) == 64


def test_owner_gate_uses_public_st_and_removes_extension_context(monkeypatch, tmp_path):
    import subprocess

    from app.services.session_ingestion.native_operator import _canonical_gate
    calls = []
    monkeypatch.setenv("ST_EXTENSION_CONTEXT", "recursive-untrusted-context")
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"state":"success"}', stderr="")
    monkeypatch.setattr("app.services.session_ingestion.native_operator.run_process", run)
    assert _canonical_gate(tmp_path / "backend") == {"state": "success"}
    command, arguments = calls[0]
    assert command == ["st", "check", "--acceptance", "--sha", "HEAD", "--json"]
    assert arguments["cwd"] == tmp_path and "ST_EXTENSION_CONTEXT" not in arguments["env"]
