"""Actual PostgreSQL serialization of native parser cursors and model evidence."""

import asyncio
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import _get_async_url
from app.models import Session
from app.services.session_ingestion.adapters.codex import CodexTranscriptAdapter
from app.services.session_ingestion.models import (
    SessionHeartbeatRequest,
    SessionUpsertRequest,
    TranscriptIngestRequest,
)
from app.services.session_ingestion.service import (
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)


def _record(kind: str, payload: dict) -> str:
    return json.dumps({"type": kind, "timestamp": "2026-09-30T15:00:00Z", "payload": payload}) + "\n"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("with_events", [False, True])
async def test_overlapping_refresh_and_stale_metadata_writers_preserve_latest_turn(
    tmp_path: Path, with_events: bool,
) -> None:
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test", "Integration writes require the isolated test database"
    engine = create_async_engine(url)
    if with_events:
        async with engine.connect() as connection:
            columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("session_events"))
        if "call_id" not in {column["name"] for column in columns}:
            await engine.dispose()
            pytest.skip("Isolated test DB predates existing native event provenance migration (call_id missing)")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = str(uuid.uuid4())
    path = tmp_path / "native.jsonl"
    initial = (
        _record("session_meta", {"id": session_id, "session_id": session_id})
        + _record("event_msg", {"type": "task_started", "turn_id": "first"})
        + _record("turn_context", {"turn_id": "first", "model": "old-request"})
        + _record("response_item", {"type": "message", "role": "assistant", "model": "old-served", "content": [{"type": "output_text", "text": "first"}] if with_events else []})
    )
    path.write_text(initial)
    first_parsed, second_parsed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = CodexTranscriptAdapter.read_new_events
    parse_count = 0

    async def paused_read(adapter, session_ref, checkpoint=None):
        nonlocal parse_count
        parse_count += 1
        result = await original(adapter, session_ref, checkpoint)
        if parse_count == 1:
            first_parsed.set()
            await release.wait()
        else:
            second_parsed.set()
        return result

    try:
        async with factory() as seed:
            seed.add(Session(
                id=session_id, project_id="agent-hub", provider="codex", model="codex/unknown",
                status="active", session_type="agent", provider_metadata={"transcript_path": str(path)},
            ))
            await seed.commit()
        async with factory() as db1, factory() as db2, factory() as stale_heartbeat_db, factory() as stale_upsert_db:
            first_row = await db1.get(Session, session_id)
            second_row = await db2.get(Session, session_id)
            heartbeat_row = await stale_heartbeat_db.get(Session, session_id)
            upsert_row = await stale_upsert_db.get(Session, session_id)
            assert heartbeat_row is not None and upsert_row is not None
            request = TranscriptIngestRequest(provider="codex", transcript_path=str(path))
            with patch.object(CodexTranscriptAdapter, "read_new_events", paused_read):
                first = asyncio.create_task(ingest_transcript_events(db1, session_id, request, session=first_row))
                await asyncio.wait_for(first_parsed.wait(), 5)
                second = asyncio.create_task(ingest_transcript_events(db2, session_id, request, session=second_row))
                try:
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(second_parsed.wait(), 0.1)
                    path.write_text(initial + _record("event_msg", {"type": "task_started", "turn_id": "latest"}) + _record("turn_context", {"turn_id": "latest", "model": "gpt-6.1-sol", "effort": "high"}))
                finally:
                    release.set()
                first_result, latest_result = await asyncio.wait_for(asyncio.gather(first, second), 10)
            assert first_result.model_evidence is not None and latest_result.model_evidence is not None
            assert first_result.model_evidence.observed_model == "old-served"
            assert latest_result.model_evidence.turn_id == "latest"
            assert latest_result.model_evidence.requested_model == "gpt-6.1-sol"
            assert latest_result.model_evidence.observed_model is None
            latest_checkpoint = latest_result.next_checkpoint
            assert heartbeat_row.provider_metadata is not None and upsert_row.provider_metadata is not None
            assert "model_evidence" not in heartbeat_row.provider_metadata
            assert "model_evidence" not in upsert_row.provider_metadata
            await heartbeat_session(stale_heartbeat_db, session_id, SessionHeartbeatRequest(summary="alive"), session=heartbeat_row)
            with patch("app.services.session_ingestion.service._validate_project_id", return_value=None):
                await upsert_session(stale_upsert_db, SessionUpsertRequest(
                    session_id=session_id, project_id="agent-hub", provider="codex", model="codex/stale-request",
                    provider_metadata={"transcript_path": str(path)},
                ))
        async with factory() as verify:
            persisted = await verify.get(Session, session_id)
            assert persisted is not None and persisted.provider_metadata is not None
            assert persisted.model == "codex/unknown"
            assert persisted.provider_metadata["model_evidence"]["turn_id"] == "latest"
            assert persisted.provider_metadata["transcript_ingestion"]["checkpoint"] == latest_checkpoint
    finally:
        release.set()
        async with factory() as cleanup:
            await cleanup.execute(delete(Session).where(Session.id == session_id))
            await cleanup.commit()
        await engine.dispose()
