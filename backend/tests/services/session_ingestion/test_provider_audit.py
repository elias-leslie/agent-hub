"""Regressions reproduced by the supported-provider source audit."""

import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import _get_async_url
from app.models import Session, SessionEvent
from app.services.event_storage import store_event
from app.services.session_ingestion.adapters.transcript_parsers import parse_transcript_events
from app.services.session_ingestion.models import TranscriptIngestRequest
from app.services.session_ingestion.service import ingest_transcript_events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_claude_refresh_preserves_native_events_beside_hooks_and_replays_redaction(
    tmp_path: Path,
) -> None:
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = str(uuid.uuid4())
    transcript = tmp_path / "claude.jsonl"
    record = {"type": "assistant", "uuid": "native-record", "sessionId": session_id,
              "timestamp": "2026-10-19T02:00:00Z", "message": {
                  "id": "message-1", "model": "claude-opus-5-5", "content": [
                      {"type": "text", "text": "Synthetic key: " + "sk-ant-" + "x" * 24},
                      {"type": "tool_use", "id": "call-native", "name": "Read", "input": {"file_path": "/tmp/example"}},
                  ]}}
    transcript.write_text(json.dumps(record) + "\n")
    try:
        async with factory() as db:
            session = Session(id=session_id, project_id="agent-hub", provider="anthropic",
                              model="unknown", status="completed", session_type="claude_code",
                              provider_metadata={"transcript_path": str(transcript)})
            db.add(session)
            await db.flush()
            hook = await store_event(db, session_id, "tool_use", turn=1, sequence=1,
                                     tool_name="Read", session=session)
            await db.commit()
            request = TranscriptIngestRequest(provider="claude", transcript_path=str(transcript))
            result = await ingest_transcript_events(db, session_id, request, session=session)
            assert result.events_appended == 2  # A hook's sequence is not native identity.
            rows = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session_id))).scalars().all()
            assert hook.id in {row.id for row in rows}
            assert [row.call_id for row in rows if row.source_event_id and row.event_type == "tool_use"] == ["call-native"]
            assert all("sk-ant-" not in (row.content or "") for row in rows)
            ids = {row.id for row in rows}
            # A lost client cursor is safe, including after redaction at storage.
            again = await ingest_transcript_events(db, session_id, request, session=session)
            assert again.events_appended == 0
            assert {row.id for row in (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session_id))).scalars()} == ids
            # The backend and host can see different st_dev values for this
            # exact file. Replaying it must find the same retained records.
            native = [row for row in rows if row.source_event_id]
            for row in native:
                assert row.source_event_id is not None
                row.source_event_id = re.sub(r"^([^:]+):[0-9]+:", r"\g<1>:999999:", row.source_event_id)
            metadata = dict(session.provider_metadata or {})
            retained = dict(metadata["transcript_ingestion"])
            cursor = json.loads(retained["checkpoint"])
            cursor["device"] += 1
            retained["checkpoint"] = json.dumps(cursor)
            metadata["transcript_ingestion"] = retained
            session.provider_metadata = metadata
            await db.commit()
            replay = await ingest_transcript_events(db, session_id, request, session=session)
            assert replay.events_appended == 0

            # Recover a proven duplicate written by the older mount-sensitive
            # projection. Preserve all original IDs, including the hook.
            original = native[0]
            assert original.source_event_id is not None
            duplicate = SessionEvent(
                session_id=session_id, turn=original.turn, sequence=99,
                event_type=original.event_type, role=original.role, content=original.content,
                tool_name=original.tool_name, call_id=original.call_id,
                tool_input=original.tool_input, tool_output=original.tool_output,
                model_used=original.model_used, source_timestamp=original.source_timestamp,
                source_event_id=re.sub(r"^([^:]+):[0-9]+:", r"\g<1>:888888:", original.source_event_id),
            )
            db.add(duplicate)
            await db.commit()
            repair = await ingest_transcript_events(db, session_id, request, session=session, repair_projection=True)
            assert repair.events_deduplicated == 1
            assert {row.id for row in (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session_id))).scalars()} == ids
            repeated = await ingest_transcript_events(db, session_id, request, session=session, repair_projection=True)
            assert repeated.events_deduplicated == repeated.events_appended == 0
    finally:
        async with factory() as db:
            await db.execute(delete(Session).where(Session.id == session_id))
            await db.commit()
        await engine.dispose()


@pytest.mark.unit
def test_native_lifecycle_settings_and_compaction_retain_only_public_facts() -> None:
    events = parse_transcript_events([json.dumps(record) for record in [
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-a"}},
        {"type": "turn_context", "payload": {"turn_id": "turn-a", "model": "requested-model",
         "effort": "high", "cyber_access_program": "off", "developer_instructions": "private-context"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-a",
         "last_agent_message": "private-context"}},
        {"type": "compacted", "payload": {"compaction_response_id": "compaction-a",
         "replacement_history": "private-context"}},
        {"type": "system", "subtype": "compact_boundary", "uuid": "claude-compact",
         "compactMetadata": {"trigger": "auto", "preTokens": 100}, "content": "private-context"},
    ]])
    assert [event.event_type for event in events] == [
        "native_lifecycle", "native_settings", "native_lifecycle", "native_lifecycle", "native_lifecycle",
    ]
    assert events[1].tool_output == {
        "source": "codex.turn_context", "native_turn_id": "turn-a",
        "requested_model": "requested-model", "reasoning_effort": "high", "cyber_access_program": "off",
    }
    assert events[2].tool_output is not None
    assert events[2].tool_output["status"] == "completed"
    assert "private-context" not in str(events)


