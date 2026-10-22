"""Sanitized Pi v3 transcript evidence; never calls a model or the live DB."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.session_ingestion._events import _adapter_for_provider
from app.services.session_ingestion.adapters.base import ProviderSessionRef
from app.services.session_ingestion.adapters.transcript_parsers import (
    inspect_transcript_source,
    read_incremental_transcript_events,
)
from app.services.session_ingestion.pi_sync import pi_header, sync_pi_session

SID = "00000000-0000-4000-8000-000000000001"
MODEL = "gpt-6.1-sol"
PROVIDER = "openai-codex"


def record(kind, id, **fields):
    return {"type": kind, "id": id, "parentId": None, "timestamp": "2026-10-22T12:00:00Z", **fields}


@pytest.fixture
def transcript(tmp_path):
    rows = [
        record("session", SID, version=3, cwd="/fixture/project"),
        record("model_change", "selected", provider=PROVIDER, modelId=MODEL),
        record("thinking_level_change", "thinking", thinkingLevel="xhigh"),
        record("message", "user", message={"role": "user", "content": [{"type": "text", "text": "Read fixture"}]}),
        record("message", "response", message={"role": "assistant", "provider": PROVIDER, "model": MODEL,
            "content": [{"type": "thinking", "thinking": "Inspect fixture"},
                        {"type": "toolCall", "id": "call-1", "name": "read", "arguments": {"path": "fixture.py"}}],
            "usage": {"input": 10, "output": 4, "cacheRead": 6, "cacheWrite": 2, "totalTokens": 22,
                      "cost": {"total": 0.001}}}),
        record("message", "tool", message={"role": "toolResult", "toolCallId": "call-1", "toolName": "read",
            "content": [{"type": "text", "text": "fixture"}], "isError": False,
            "usage": {"input": 2, "output": 1, "cacheRead": 3, "cacheWrite": 0, "totalTokens": 6}}),
        record("message", "answer", message={"role": "assistant", "provider": PROVIDER, "model": MODEL,
            "content": [{"type": "text", "text": "Read."}],
            "usage": {"input": 20, "output": 3, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 23}}),
    ]
    path = tmp_path / "pi.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.mark.parametrize("provider", ["openai-codex", "openai"])
def test_pi_events_usage_and_incremental_replay(transcript, provider):
    transcript.write_text(transcript.read_text().replace(PROVIDER, provider))
    events, checkpoint = read_incremental_transcript_events(str(transcript))
    assert [event.event_type for event in events] == [
        "user_message", "thinking", "tool_use", "usage", "tool_result", "usage", "assistant_message", "usage"]
    assert events[2].call_id == events[4].call_id == "call-1"
    assert events[2].tool_input == {"path": "fixture.py"}
    assert events[3].model_used == f"{provider}/{MODEL}"
    usage = [event.usage for event in events if event.event_type == "usage" and event.usage is not None]
    assert sum(row["input_tokens"] for row in usage) == 43
    assert sum(row["output_tokens"] for row in usage) == 8
    assert sum(row["cached_input_tokens"] for row in usage) == 9
    assert usage[1]["response_id"] == "tool"
    assert events[5].model_used is None  # Nested tool usage need not name one model.
    assert usage[0]["native"]["cost"]["total"] == 0.001
    assert all(row["scope"] == "response" and row["source"] == "pi.transcript" for row in usage)
    assert read_incremental_transcript_events(str(transcript), checkpoint) == ([], checkpoint)
    assert inspect_transcript_source(str(transcript), checkpoint).state == "ready"

    row = record("message", "next-user", message={"role": "user", "content": "Next"})
    with transcript.open("a") as handle:
        handle.write(json.dumps(row))
    assert read_incremental_transcript_events(str(transcript), checkpoint)[0] == []
    with transcript.open("a") as handle:
        handle.write("\n")
    delta, _ = read_incremental_transcript_events(str(transcript), checkpoint)
    assert len(delta) == 1 and delta[0].turn == 2 and delta[0].content == "Next"


def test_failed_pi_response_has_zero_native_usage(transcript):
    failed = record("message", "failed", message={"role": "assistant", "provider": PROVIDER, "model": MODEL,
        "content": [], "stopReason": "error", "errorMessage": "fixture authentication unavailable",
        "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0}})
    transcript.write_text(json.dumps(failed) + "\n")
    events, _ = read_incremental_transcript_events(str(transcript))
    assert events[0].event_type == "error"
    assert events[1].usage is not None
    assert events[1].usage["input_tokens"] == events[1].usage["output_tokens"] == 0


def test_pi_source_identity_and_root_checks(transcript, monkeypatch):
    assert pi_header(str(transcript), SID)[1]["id"] == SID
    with pytest.raises(ValueError, match="identity"):
        pi_header(str(transcript), "another-session")
    monkeypatch.setenv("AGENT_HUB_TRANSCRIPT_ROOTS", str(transcript.parent / "other"))
    with pytest.raises(ValueError, match="roots"):
        pi_header(str(transcript), SID)


@pytest.mark.asyncio
async def test_pi_fork_does_not_charge_copied_history(transcript):
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    fork = transcript.with_name("fork.jsonl")
    fork_id = "00000000-0000-4000-8000-000000000002"
    rows[0] = record("session", fork_id, version=3, cwd="/fixture/project", parentSession=str(transcript))
    rows.append(record("message", "fork-answer", message={"role": "assistant", "provider": PROVIDER,
        "model": MODEL, "content": [{"type": "text", "text": "Fresh fork answer"}],
        "usage": {"input": 5, "output": 2, "cacheRead": 0, "cacheWrite": 0}}))
    fork.write_text("".join(json.dumps(row) + "\n" for row in rows))
    adapter = _adapter_for_provider("pi")
    events, checkpoint = await adapter.read_new_events(ProviderSessionRef(provider_session_id=fork_id, source_id=str(fork)))
    assert [event.event_type for event in events] == ["assistant_message", "usage"]
    assert events[-1].usage is not None and events[-1].usage["input_tokens"] == 5
    assert (await adapter.read_new_events(ProviderSessionRef(provider_session_id=fork_id, source_id=str(fork)), checkpoint))[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("work_role", [None, {"id": "implementation", "source": "tether:root:fixture"}])
@pytest.mark.parametrize("phase,status", [("working", "active"), ("idle", "active"), ("shutdown", "completed")])
async def test_pi_sync_uses_canonical_ingestion_and_native_identity(transcript, monkeypatch, phase, status, work_role):
    from app.services.session_ingestion import pi_sync

    db = AsyncMock()
    result = MagicMock()
    session = SimpleNamespace(id=SID, provider_metadata={})
    result.scalar_one_or_none.side_effect = [None, session]
    db.execute.return_value = result
    upsert = AsyncMock(return_value=(session, None))
    ingest = AsyncMock(return_value=SimpleNamespace(events_appended=7, events_skipped=0))
    heartbeat = AsyncMock()
    monkeypatch.setattr(pi_sync, "upsert_session", upsert)
    monkeypatch.setattr(pi_sync, "ingest_transcript_events", ingest)
    monkeypatch.setattr(pi_sync, "heartbeat_session", heartbeat)
    receipt = await sync_pi_session(db, session_id=SID, transcript=str(transcript), project_id="agent-hub",
        cwd="/fixture/project", provider=PROVIDER, model=MODEL, phase=phase, aico_session_id="widget-session", work_role=work_role)
    assert upsert.await_args is not None
    request = upsert.await_args.args[1]
    assert request.session_id == SID and request.session_type == "pi"
    assert request.provider == PROVIDER and request.model == f"{PROVIDER}/unknown"
    assert request.provider_metadata.get("work_role") == work_role
    assert request.provider_metadata["aico_session_id"] == "widget-session"
    assert request.provider_metadata["pi_selection"] == {"provider": PROVIDER, "model": MODEL}
    assert ingest.await_args is not None
    assert ingest.await_args.args[2].provider == "pi"
    assert receipt["events_appended"] == 7
    heartbeat.assert_awaited_once()
    assert heartbeat.await_args is not None
    assert heartbeat.await_args.args[2].status == status
    assert heartbeat.await_args.args[2].phase == phase
    assert _adapter_for_provider("pi").provider_name == "pi"


@pytest.mark.asyncio
async def test_pi_retirement_is_exact_and_idempotent(transcript, monkeypatch):
    from app.services.session_ingestion import pi_sync

    owner = "aico-widget-12345678"
    session = SimpleNamespace(id=SID, project_id="agent-hub", provider_metadata={
        "transcript_path": str(transcript), "cwd": "/fixture/project",
        "pi_selection": {"provider": PROVIDER, "model": MODEL}})
    db = AsyncMock()
    result = MagicMock()
    legacy = SimpleNamespace(id="legacy", provider_metadata={})
    result.scalars.return_value.all.return_value = [legacy, session]
    db.execute.return_value = result

    async def sync(_db, **kwargs):
        assert kwargs == {"session_id": SID, "project_id": "agent-hub", "transcript": str(transcript),
            "cwd": "/fixture/project", "provider": PROVIDER, "model": MODEL,
            "phase": "shutdown", "aico_session_id": owner, "retired_by_tether": True}
        session.provider_metadata["tether_retired"] = True

    sync_mock = AsyncMock(side_effect=sync)
    monkeypatch.setattr(pi_sync, "sync_pi_session", sync_mock)
    first = await pi_sync.retire_pi_sessions(db, owner)
    assert first["closed_session_ids"] == [SID]
    assert first["unavailable_session_ids"] == ["legacy"]
    query = db.execute.await_args.args[0]
    assert set(query.compile().params.values()) >= {owner, "pi", "harness", "aico_session_id"}
    assert (await pi_sync.retire_pi_sessions(db, owner))["closed_session_ids"] == []
    sync_mock.assert_awaited_once()
    with pytest.raises(ValueError, match="exact Tether"):
        await pi_sync.retire_pi_sessions(db, "another-owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_by_tether", [False, True])
async def test_late_idle_sync_cannot_reopen_retired_pi_or_drop_correlation(transcript, monkeypatch, retired_by_tether):
    from app.services.session_ingestion import pi_sync

    metadata = {"transcript_path": str(transcript), "aico_session_id": "aico-widget-12345678"}
    existing = SimpleNamespace(id=SID, session_type="pi", model=f"{PROVIDER}/{MODEL}", provider_metadata=metadata)
    latest = SimpleNamespace(id=SID, provider_metadata={**metadata, "tether_retired": not retired_by_tether})
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.side_effect = [existing, latest]
    db.execute.return_value = result
    upsert = AsyncMock(return_value=(existing, None))
    monkeypatch.setattr(pi_sync, "upsert_session", upsert)
    monkeypatch.setattr(pi_sync, "ingest_transcript_events", AsyncMock(return_value=SimpleNamespace(events_appended=0, events_skipped=7)))
    heartbeat = AsyncMock()
    monkeypatch.setattr(pi_sync, "heartbeat_session", heartbeat)
    receipt = await sync_pi_session(db, session_id=SID, transcript=str(transcript), project_id="agent-hub",
        cwd="/fixture/project", provider=PROVIDER, model=MODEL, phase="idle", retired_by_tether=retired_by_tether)
    assert upsert.await_args is not None
    assert heartbeat.await_args is not None
    assert db.execute.await_args is not None
    assert upsert.await_args.args[1].provider_metadata["aico_session_id"] == metadata["aico_session_id"]
    assert receipt["phase"] == "shutdown"
    assert heartbeat.await_args.args[2].status == "completed"
    assert heartbeat.await_args.args[2].provider_metadata == ({"tether_retired": True} if retired_by_tether else {})
    assert heartbeat.await_args.kwargs["session"] is latest
    assert db.execute.await_args.args[0]._for_update_arg is not None
