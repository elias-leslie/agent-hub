"""Native Codex roles, terminal errors, and execution identity stay faithful."""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import _get_async_url
from app.models import Session, SessionEvent
from app.services.event_storage import store_event
from app.services.session_ingestion.adapters.transcript_parsers import (
    parse_transcript_events,
    read_incremental_transcript_events,
)
from app.services.session_ingestion.models import TranscriptIngestRequest
from app.services.session_ingestion.service import ingest_transcript_events


@pytest.mark.unit
@pytest.mark.parametrize(
    ("role", "event_type"),
    [("developer", "system_message"), ("system", "system_message")],
)
def test_injected_instructions_keep_their_native_role(role: str, event_type: str) -> None:
    events = parse_transcript_events([json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message", "id": "injected", "role": role,
            "content": [
                {"type": "input_text", "text": "Follow the project instructions."},
                {"type": "encrypted_content", "encrypted_content": "sealed-private-payload"},
                {"type": "input_text", "text": "Keep the assigned scope."},
            ],
        },
    })])

    assert [(event.event_type, event.role) for event in events] == [(event_type, role)] * 2
    assert [event.source_event_id for event in events] == [
        "response_item:injected:1", "response_item:injected:2",
    ]
    assert "sealed-private-payload" not in str(events)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("device_changed", [False, True])
async def test_refresh_repairs_legacy_projection_without_replaying_executions(
    tmp_path: Path, device_changed: bool,
) -> None:
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = str(uuid.uuid4())
    transcript = tmp_path / "native.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": session_id}},
        {"type": "response_item", "payload": {
            "type": "message", "id": "instructions", "role": "developer",
            "content": [{"type": "input_text", "text": "Keep the assigned scope."}],
        }},
        {"type": "response_item", "payload": {
            "type": "message", "id": "user", "role": "user",
            "content": [{"type": "input_text", "text": "Inspect the local fixture."}],
        }},
        # Equal commands with different native IDs are distinct invocations.
        *[{"type": "response_item", "payload": {
            "type": "function_call", "id": f"function-{index}", "call_id": f"call-{index}",
            "name": "exec_command", "arguments": '{"cmd":"pwd"}',
        }} for index in range(2)],
        {"type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "failed-turn",
            "error": {"message": "Native task failed.", "codex_error_info": "cyber_policy"},
        }},
    ]
    transcript.write_text("".join(json.dumps(record) + "\n" for record in records))
    events, checkpoint = read_incremental_transcript_events(str(transcript))
    legacy_checkpoint = json.loads(checkpoint or "{}")
    legacy_checkpoint["sequence"] -= 1  # The old parser dropped task_complete.error.
    if device_changed:
        legacy_checkpoint["device"] += 1  # Same inode after the native home mount changed.
    request = TranscriptIngestRequest(provider="codex", transcript_path=str(transcript))
    try:
        async with factory() as db:
            session = Session(
                id=session_id, project_id="agent-hub", provider="codex", model="codex/unknown",
                status="completed", session_type="agent", provider_metadata={
                    "transcript_path": str(transcript),
                    "transcript_ingestion": {"checkpoint": json.dumps(legacy_checkpoint)},
                },
            )
            db.add(session)
            await db.flush()
            for event in events:
                if event.event_type == "error":
                    continue
                values = event.model_dump(exclude={"native_observation"})
                if event.event_type == "system_message":
                    values.update(event_type="assistant_message", role="assistant")
                await store_event(db, session_id, **values, session=session)
            await store_event(db, session_id, event_type="memory_cite", content="Keep this hook event.", session=session)
            await db.commit()
            before = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session_id))).scalars().all()
            before_ids = {event.id for event in before}
            original_activity = session.last_activity_at
            assert session.provider_metadata is not None
            original_live = dict(session.provider_metadata.get("live_activity") or {})
            with patch("app.services.session_ingestion.service._validate_project_id", return_value=None):
                repaired = await ingest_transcript_events(db, session_id, request, session=session, repair_projection=True)
                repeated = await ingest_transcript_events(db, session_id, request, session=session, repair_projection=True)
            assert repaired.events_updated == 1
            assert repaired.events_appended == 1
            assert repaired.next_checkpoint is not None
            assert repaired.last_sequence == json.loads(repaired.next_checkpoint)["sequence"]
            assert repeated.events_updated == repeated.events_appended == 0
            after = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session_id))).scalars().all()
            assert before_ids <= {event.id for event in after}
            assert [(event.event_type, event.role) for event in after if event.source_event_id == "response_item:instructions:1"] == [("system_message", "developer")]
            assert sorted(event.call_id for event in after if event.event_type == "tool_use") == ["call-0", "call-1"]
            assert len([event for event in after if event.event_type == "error"]) == 1
            assert len([event for event in after if event.event_type == "memory_cite"]) == 1
            assert session.last_activity_at == original_activity
            assert session.provider_metadata is not None
            assert session.provider_metadata.get("live_activity") == original_live
            # A later native event must not collide with the backfilled error or hook.
            with transcript.open("a") as output:
                output.write(json.dumps({"type": "response_item", "payload": {
                    "type": "function_call", "id": "later", "call_id": "call-later",
                    "name": "exec_command", "arguments": '{"cmd":"pwd"}',
                }}) + "\n")
            with patch("app.services.session_ingestion.service._validate_project_id", return_value=None):
                later = await ingest_transcript_events(db, session_id, request, session=session)
            assert later.events_appended == 1
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(Session).where(Session.id == session_id))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.unit
def test_task_completion_error_reaches_the_error_view_without_repeating_final_text() -> None:
    events = parse_transcript_events([
        json.dumps({"type": "event_msg", "timestamp": "2026-10-21T23:08:09Z", "payload": {
            "type": "task_complete", "turn_id": "failed-turn", "last_agent_message": None,
            "error": {
                "message": "This content was flagged for possible cybersecurity risk.",
                "codex_error_info": "cyber_policy",
                "encrypted_content": "sealed-private-payload",
            },
        }}),
        json.dumps({"type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "successful-turn",
            "last_agent_message": "Already projected from the assistant response.",
        }}),
    ])

    errors = [event for event in events if event.event_type == "error"]
    assert len(errors) == 1
    error = errors[0]
    assert [event.tool_output["status"] for event in events if event.event_type == "native_lifecycle" and event.tool_output] == ["failed", "completed"]
    assert error.event_type == "error"
    assert "cyber_policy" in (error.content or "")
    assert "flagged for possible cybersecurity risk" in (error.content or "")
    assert error.tool_output == {"codex_error_info": "cyber_policy", "turn_id": "failed-turn"}
    assert error.source_timestamp is not None
    assert error.source_event_id == "event_msg:line:0:1"
    assert "sealed-private-payload" not in str(events)
