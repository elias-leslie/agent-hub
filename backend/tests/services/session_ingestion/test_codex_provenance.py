"""Native ingress conflicts are rejected before persistent mutation."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Session
from app.services.session_ingestion.models import (
    SessionHeartbeatRequest,
    SessionUpsertRequest,
    TranscriptIngestRequest,
)
from app.services.session_ingestion.service import (
    SessionIngestionConflict,
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)


def _session(path: Path, **metadata: object) -> Session:
    return Session(
        id="child", project_id="agent-hub", provider="codex", model="codex/old",
        parent_session_id="root", session_type="agent", status="active",
        provider_metadata={"transcript_path": str(path), **metadata},
    )


def _native(path: Path, **overrides: object) -> None:
    header = {
        "id": "child", "session_id": "root", "parent_thread_id": "root",
        "agent_path": "/root/child", "cwd": "/srv/workspaces/projects/agent-hub",
        **overrides,
    }
    path.write_text(json.dumps({"type": "session_meta", "payload": header}) + "\n")


@pytest.mark.parametrize(("metadata", "header", "code"), [
    ({"external_identity": {"runtime_session_id": "root"}}, {}, "session_runtime_identity_mismatch"),
    ({"external_identity": {"agent_path": "/root/other"}}, {}, "transcript_agent_path_mismatch"),
    ({"project_id": "other"}, {}, "session_project_provenance_mismatch"),
    ({"model_evidence": {"session_id": "root"}}, {}, "session_model_evidence_identity_mismatch"),
    ({"native_session_id": "other"}, {}, "transcript_runtime_identity_mismatch"),
    ({}, {"parent_thread_id": "other"}, "transcript_parent_mismatch"),
    ({}, {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "other"}}}}, "transcript_provenance_conflict"),
    ({}, {"cwd": "/srv/workspaces/projects/other"}, "transcript_project_mismatch"),
])
@pytest.mark.asyncio
async def test_transcript_conflicts_do_not_append_or_commit(
    tmp_path: Path, metadata: dict, header: dict, code: str,
) -> None:
    path = tmp_path / "native.jsonl"
    _native(path, **header)
    session = _session(path, **metadata)
    db = AsyncMock()
    db.get.return_value = Session(id="root", project_id="agent-hub")
    with (
        patch("app.services.session_ingestion.service.append_normalized_events", new_callable=AsyncMock) as append,
        patch("app.services.session_ingestion._native_provenance.get_known_roots", return_value={
            "agent-hub": "/srv/workspaces/projects/agent-hub", "other": "/srv/workspaces/projects/other",
        }),
        pytest.raises(SessionIngestionConflict) as denied,
    ):
        await ingest_transcript_events(db, session.id, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
    assert denied.value.code == code
    append.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_registration_preserves_server_evidence_and_rejects_identity_replacement(tmp_path: Path) -> None:
    path = tmp_path / "native.jsonl"
    _native(path)
    server_evidence = {"session_id": "child", "observed_model": "served"}
    session = _session(path, model_evidence=server_evidence, transcript_ingestion={"checkpoint": "server"}, external_identity={"agent_path": "/root/child"})
    parent = Session(id="root", project_id="agent-hub")
    db = AsyncMock()
    db.get.return_value = parent
    db.add = MagicMock()
    with (
        patch("app.services.session_ingestion.service._validate_project_id", new_callable=AsyncMock),
        patch("app.services.session_ingestion.service.get_or_create_session", new_callable=AsyncMock, side_effect=[(session, True), (parent, True)]),
    ):
        await upsert_session(db, SessionUpsertRequest(
            session_id="child", parent_session_id="root", project_id="agent-hub", provider="codex", model="codex/requested",
            provider_metadata={"transcript_path": str(path), "model_evidence": {"session_id": "child", "observed_model": "copied"}, "transcript_ingestion": {"checkpoint": "copied"}},
        ))
    assert session.provider_metadata is not None
    assert session.provider_metadata["model_evidence"] == server_evidence
    assert session.model == "codex/unknown"  # Stale metadata without native freshness cannot deliver a model.
    assert session.models_used == []
    assert session.provider_metadata["transcript_ingestion"]["checkpoint"] == "server"
    with pytest.raises(SessionIngestionConflict) as denied:
        await heartbeat_session(db, session.id, SessionHeartbeatRequest(provider_metadata={"external_identity": {"agent_path": "/root/other"}}), session=session)
    assert denied.value.code == "session_provenance_immutable"
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_stale_client_cursor_uses_canonical_server_evidence_cursor(tmp_path: Path) -> None:
    from app.services.session_ingestion.adapters.transcript_parsers import (
        read_incremental_transcript_events,
    )

    path = tmp_path / "native.jsonl"
    _native(path)
    _, checkpoint = read_incremental_transcript_events(str(path))
    session = _session(path, transcript_ingestion={"checkpoint": checkpoint})
    db = AsyncMock()
    db.get.return_value = Session(id="root", project_id="agent-hub")
    append_result = MagicMock(events_appended=0, events_skipped=0, last_turn=1, last_sequence=0, event_ids=[])
    with (
        patch("app.services.session_ingestion.service.append_normalized_events", new_callable=AsyncMock, return_value=append_result),
        patch("app.services.session_ingestion.service._reconcile_transcript_session_scope", new_callable=AsyncMock),
    ):
        result = await ingest_transcript_events(db, session.id, TranscriptIngestRequest(
            provider="codex", transcript_path=str(path), checkpoint="forged-or-stale-client-state",
        ), session=session)
    assert result.next_checkpoint == checkpoint
    assert session.model == "codex/unknown"
    assert result.model_evidence is not None
    assert result.model_evidence.observed_model is None


@pytest.mark.asyncio
async def test_legacy_cross_project_native_parent_is_rejected_before_append(tmp_path: Path) -> None:
    path = tmp_path / "native.jsonl"
    _native(path)
    session = _session(path)
    db = AsyncMock()
    db.get.return_value = Session(id="root", project_id="neri")
    with (
        patch("app.services.session_ingestion.service.append_normalized_events", new_callable=AsyncMock) as append,
        pytest.raises(SessionIngestionConflict) as denied,
    ):
        await ingest_transcript_events(db, session.id, TranscriptIngestRequest(provider="codex", transcript_path=str(path)), session=session)
    assert denied.value.code == "session_parent_project_mismatch"
    append.assert_not_awaited()
    db.commit.assert_not_awaited()
