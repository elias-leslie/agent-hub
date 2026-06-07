"""Tests for the canonical session ingestion service."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Session
from app.services.session_ingestion.models import (
    AppendNormalizedEventsRequest,
    NormalizedEvent,
    SessionHeartbeatRequest,
    SessionUpsertRequest,
    TranscriptIngestRequest,
)
from app.services.session_ingestion.service import (
    append_normalized_events,
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_serializes_batches_by_session_id() -> None:
    db = AsyncMock()

    lock_result = MagicMock()
    existing_pairs = MagicMock()
    existing_pairs.all.return_value = []
    db.execute = AsyncMock(side_effect=[lock_result, existing_pairs])

    stored_event = MagicMock()
    stored_event.id = "evt-locked"

    with (
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion._events.get_max_sequence",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "app.services.session_ingestion._events.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ),
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-lock",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=1,
                        sequence=1,
                        role="assistant",
                        content="locked",
                    ),
                ]
            ),
        )

    first_execute = db.execute.await_args_list[0]
    assert "pg_advisory_xact_lock" in str(first_execute.args[0])
    assert first_execute.args[1] == {"lock_key": "session-events:session-lock"}
    assert result.events_appended == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_skips_existing_turn_sequence_pair() -> None:
    db = AsyncMock()

    existing_pairs = MagicMock()
    existing_pairs.all.return_value = [(1, 1)]
    db.execute = AsyncMock(return_value=existing_pairs)

    stored_event = MagicMock()
    stored_event.id = "evt-2"

    with (
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion._events.get_max_sequence",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion._events.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ) as mock_store,
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-123",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=1,
                        sequence=1,
                        role="assistant",
                        content="existing",
                    ),
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=1,
                        sequence=2,
                        role="assistant",
                        content="new",
                    ),
                ]
            ),
        )

    assert result.events_appended == 1
    assert result.events_skipped == 1
    assert result.event_ids == ["evt-2"]
    mock_store.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_skips_duplicate_turn_sequence_within_same_batch() -> None:
    db = AsyncMock()

    existing_pairs = MagicMock()
    existing_pairs.all.return_value = []
    db.execute = AsyncMock(return_value=existing_pairs)

    stored_event = MagicMock()
    stored_event.id = "evt-2"

    with (
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion._events.get_max_sequence",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion._events.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ) as mock_store,
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-dup-batch",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=8,
                        sequence=2,
                        role="assistant",
                        content="first",
                    ),
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=8,
                        sequence=2,
                        role="assistant",
                        content="duplicate",
                    ),
                ]
            ),
        )

    assert result.events_appended == 1
    assert result.events_skipped == 1
    assert result.event_ids == ["evt-2"]
    mock_store.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_single_implicit_event_uses_fast_path() -> None:
    db = AsyncMock()
    session = MagicMock()
    stored_event = MagicMock()
    stored_event.id = "evt-fast"
    stored_event.turn = 4
    stored_event.sequence = 9

    with (
        patch(
            "app.services.session_ingestion._events.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ) as mock_store,
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
        ) as mock_get_max_turn,
        patch(
            "app.services.session_ingestion._events._load_existing_pairs",
            new_callable=AsyncMock,
        ) as mock_load_existing_pairs,
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-fast",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        role="assistant",
                        content="hello",
                    )
                ]
            ),
            session=session,
        )

    assert result.events_appended == 1
    assert result.events_skipped == 0
    assert result.last_turn == 4
    assert result.last_sequence == 9
    assert result.event_ids == ["evt-fast"]
    mock_store.assert_awaited_once()
    await_args = mock_store.await_args
    assert await_args is not None
    assert await_args.kwargs["session"] is session
    mock_get_max_turn.assert_not_awaited()
    mock_load_existing_pairs.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_reconciles_transcript_backed_session_models() -> None:
    db = AsyncMock()
    session = Session(
        id="session-transcript-append",
        project_id="agent-hub",
        provider="claude",
        model="opus-4-6",
        status="active",
        session_type="claude_code",
        provider_metadata={"transcript_path": "/tmp/session-transcript-append.jsonl"},
        models_used=["opus-4-6"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        return_value=MagicMock(
            all=lambda: [
                ("claude-sonnet-4-6", None),
                ("claude-sonnet-4-6", None),
            ]
        )
    )

    append_result = MagicMock(
        session_id="session-transcript-append",
        events_appended=1,
        events_skipped=0,
        last_turn=1,
        last_sequence=1,
        event_ids=["evt-transcript-append"],
    )

    with patch(
        "app.services.session_ingestion.service._store_single_implicit_event",
        new_callable=AsyncMock,
        return_value=append_result,
    ) as mock_store:
        result = await append_normalized_events(
            db=db,
            session_id="session-transcript-append",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        role="assistant",
                        content="direct",
                        model_used="claude-sonnet-4-6",
                    )
                ]
            ),
            session=session,
        )

    assert result is append_result
    assert session.model == "claude-sonnet-4-6"
    assert session.models_used == ["claude-sonnet-4-6"]
    mock_store.assert_awaited_once()
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_create_sets_timestamps_without_refresh() -> None:
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            return_value=(None, False),
        ),
    ):
        session, result = await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-new",
                project_id="agent-hub",
                provider="codex",
                model="codex/gpt-5.4",
                session_type="agent",
                current_branch="main",
            ),
        )

    assert result.created is True
    assert session.id == "session-new"
    assert session.created_at is not None
    assert session.updated_at is not None
    assert db.commit.await_count == 1
    db.refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_reactivates_existing_completed_session() -> None:
    db = AsyncMock()
    session = Session(
        id="session-existing",
        project_id="agent-hub",
        provider="anthropic",
        model="claude/external-tmux",
        status="completed",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude/external-tmux"],
        providers_used=["anthropic"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            return_value=(session, True),
        ),
    ):
        updated, result = await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-existing",
                project_id="agent-hub",
                provider="anthropic",
                model="claude/external-tmux",
                session_type="claude_code",
                current_branch="main",
            ),
        )

    assert result.created is False
    assert updated is session
    assert session.status == "active"
    assert session.updated_at is not None
    assert db.commit.await_count == 1
    db.refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_rejects_overlong_external_id() -> None:
    db = AsyncMock()

    with patch(
        "app.services.session_ingestion.service._validate_project_id",
        new_callable=AsyncMock,
    ), pytest.raises(ValueError, match="external_id exceeds max length"):
        await upsert_session(
            db=db,
            request=SessionUpsertRequest.model_construct(
                session_id="session-new",
                project_id="agent-hub",
                provider="codex",
                model="codex/gpt-5.4",
                session_type="agent",
                external_id="x" * 101,
            ),
        )

    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_session_updates_without_refresh() -> None:
    db = AsyncMock()
    session = Session(
        id="session-heartbeat",
        project_id="agent-hub",
        provider="claude",
        model="claude-sonnet-4-6",
        status="active",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude-sonnet-4-6"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: session)

    _, result = await heartbeat_session(
        db=db,
        session_id="session-heartbeat",
        request=SessionHeartbeatRequest(
            cwd="/repo",
            phase="running_tool",
            status="active",
            summary="Applying change",
            heartbeat_at=datetime.now(UTC),
            active_read_paths=["backend/app/api/sessions.py"],
        ),
    )

    assert result.updated is True
    assert session.last_heartbeat_at is not None
    metadata = session.provider_metadata
    assert isinstance(metadata, dict)
    live_activity = metadata.get("live_activity")
    assert isinstance(live_activity, dict)
    assert live_activity["phase"] == "running_tool"
    assert live_activity["last_read_path"] == "backend/app/api/sessions.py"
    assert session.updated_at is not None
    assert db.commit.await_count == 1
    db.refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_reconciles_direct_session_models_from_event_evidence() -> None:
    db = AsyncMock()
    session = Session(
        id="session-direct",
        project_id="agent-hub",
        provider="claude",
        model="claude-sonnet-4-6",
        status="active",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude-opus-4-6", "claude-sonnet-4-6"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    ("claude-sonnet-4-6", None),
                    (None, None),
                    ("claude-sonnet-4-6", None),
                ]
            ),
            MagicMock(scalar_one_or_none=lambda: session),
        ]
    )

    adapter = MagicMock()
    adapter.read_new_events = AsyncMock(return_value=([], "4"))
    adapter.detect_boundaries = AsyncMock(return_value=[])
    append_result = MagicMock(
        events_appended=0,
        events_skipped=0,
        last_turn=1,
        last_sequence=1,
        event_ids=[],
    )

    with (
        patch(
            "app.services.session_ingestion.service._adapter_for_provider",
            return_value=adapter,
        ),
        patch(
            "app.services.session_ingestion.service.append_normalized_events",
            new_callable=AsyncMock,
            return_value=append_result,
        ),
    ):
        result = await ingest_transcript_events(
            db=db,
            session_id="session-direct",
            request=TranscriptIngestRequest(
                provider="claude",
                transcript_path="/tmp/session-direct.jsonl",
            ),
        )

    assert result.next_checkpoint == "4"
    assert session.model == "claude-sonnet-4-6"
    assert session.models_used == ["claude-sonnet-4-6"]
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_preserves_delegated_model_history_from_event_evidence() -> None:
    db = AsyncMock()
    session = Session(
        id="session-delegated",
        project_id="agent-hub",
        provider="claude",
        model="unknown",
        status="active",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude-haiku-4-5"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    ("claude-sonnet-4-6", None),
                    ("claude-opus-4-6", "agent-1"),
                    ("claude-sonnet-4-6", None),
                ]
            ),
            MagicMock(scalar_one_or_none=lambda: session),
        ]
    )

    adapter = MagicMock()
    adapter.read_new_events = AsyncMock(return_value=([], "8"))
    adapter.detect_boundaries = AsyncMock(return_value=[])
    append_result = MagicMock(
        events_appended=0,
        events_skipped=0,
        last_turn=2,
        last_sequence=7,
        event_ids=[],
    )

    with (
        patch(
            "app.services.session_ingestion.service._adapter_for_provider",
            return_value=adapter,
        ),
        patch(
            "app.services.session_ingestion.service.append_normalized_events",
            new_callable=AsyncMock,
            return_value=append_result,
        ),
    ):
        await ingest_transcript_events(
            db=db,
            session_id="session-delegated",
            request=TranscriptIngestRequest(
                provider="claude",
                transcript_path="/tmp/session-delegated.jsonl",
            ),
        )

    assert session.model == "claude-sonnet-4-6"
    assert session.models_used == ["claude-sonnet-4-6", "claude-opus-4-6"]
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_reconciles_scope_from_persisted_tool_evidence_when_no_new_events() -> None:
    db = AsyncMock()
    session = Session(
        id="session-scope",
        project_id="agent-hub",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "transcript_path": "/tmp/session-scope.jsonl",
        },
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    ("codex/gpt-5.4", None),
                ]
            ),
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    (
                        "exec_command",
                        {
                            "cmd": (
                                'st feedback report infra '
                                '"Detached rebuilds stayed active while agent-hub-frontend stop timed out '
                                'and was SIGKILLed before restart. Health recovered, but systemctl status '
                                'looked hung until the transient unit disappeared, which made runtime '
                                'verification noisier than it needed to be."'
                            ),
                            "workdir": "/srv/workspaces/projects/agent-hub",
                        },
                    ),
                    (
                        "exec_command",
                        {
                            "cmd": "sed -n '1,20p' backend/app/services/session_scope.py",
                            "workdir": "/srv/workspaces/projects/agent-hub",
                        },
                    ),
                    (
                        "apply_patch",
                        {
                            "input": (
                                "*** Begin Patch\n"
                                "*** Update File: backend/app/services/ownership_inventory.py\n"
                                "@@\n"
                                "*** End Patch\n"
                            )
                        },
                    ),
                ]
            ),
        ]
    )

    adapter = MagicMock()
    adapter.read_new_events = AsyncMock(return_value=([], "12"))
    adapter.detect_boundaries = AsyncMock(return_value=[])
    append_result = MagicMock(
        events_appended=0,
        events_skipped=0,
        last_turn=3,
        last_sequence=9,
        event_ids=[],
    )

    with (
        patch(
            "app.services.session_ingestion.service._adapter_for_provider",
            return_value=adapter,
        ),
        patch(
            "app.services.session_ingestion.service.append_normalized_events",
            new_callable=AsyncMock,
            return_value=append_result,
        ),
    ):
        result = await ingest_transcript_events(
            db=db,
            session_id="session-scope",
            request=TranscriptIngestRequest(
                provider="codex",
                transcript_path="/tmp/session-scope.jsonl",
            ),
        )

    assert result.next_checkpoint == "12"
    assert session.observed_read_paths == ["backend/app/services/session_scope.py"]
    assert session.observed_write_paths == ["backend/app/services/ownership_inventory.py"]
    assert session.scope_confidence == "observed_write"
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_upgrades_unknown_scope_confidence_from_stored_paths() -> None:
    db = AsyncMock()
    session = Session(
        id="session-scope-upgrade",
        project_id="agent-hub",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "transcript_path": "/tmp/session-scope-upgrade.jsonl",
        },
        observed_write_paths=["backend/app/services/session_scope.py"],
        scope_confidence="unknown",
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(all=lambda: [("codex/gpt-5.4", None)]),
            MagicMock(scalar_one_or_none=lambda: session),
        ]
    )

    adapter = MagicMock()
    adapter.read_new_events = AsyncMock(return_value=([], "13"))
    adapter.detect_boundaries = AsyncMock(return_value=[])
    append_result = MagicMock(
        events_appended=0,
        events_skipped=0,
        last_turn=3,
        last_sequence=10,
        event_ids=[],
    )

    with (
        patch(
            "app.services.session_ingestion.service._adapter_for_provider",
            return_value=adapter,
        ),
        patch(
            "app.services.session_ingestion.service.append_normalized_events",
            new_callable=AsyncMock,
            return_value=append_result,
        ),
    ):
        result = await ingest_transcript_events(
            db=db,
            session_id="session-scope-upgrade",
            request=TranscriptIngestRequest(
                provider="codex",
                transcript_path="/tmp/session-scope-upgrade.jsonl",
            ),
        )

    assert result.next_checkpoint == "13"
    assert session.scope_confidence == "observed_write"
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_session_backfills_request_identity_and_source_metadata() -> None:
    db = AsyncMock()
    session = Session(
        id="session-heartbeat-identity",
        project_id="agent-hub",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
        provider_metadata={},
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: session)

    await heartbeat_session(
        db=db,
        session_id="session-heartbeat-identity",
        request=SessionHeartbeatRequest(
            client_id="client-123",
            request_source="codex-transcript-sync",
            provider_metadata={
                "source_client": "summitflow/codex-session-sync",
                "source_path": "/home/demo/bin/codex-session-sync.py",
            },
        ),
    )

    assert session.client_id == "client-123"
    assert session.request_source == "codex-transcript-sync"
    metadata = session.provider_metadata
    assert isinstance(metadata, dict)
    assert metadata["source_client"] == "summitflow/codex-session-sync"
    assert metadata["source_path"] == "/home/demo/bin/codex-session-sync.py"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_session_reactivates_completed_session() -> None:
    db = AsyncMock()
    session = Session(
        id="session-heartbeat-completed",
        project_id="agent-hub",
        provider="anthropic",
        model="claude/external-tmux",
        status="completed",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude/external-tmux"],
        providers_used=["anthropic"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: session)

    await heartbeat_session(
        db=db,
        session_id="session-heartbeat-completed",
        request=SessionHeartbeatRequest(
            cwd="/repo",
            phase="running_tool",
            status="active",
            summary="External tmux session is running",
            heartbeat_at=datetime.now(UTC),
        ),
    )

    assert session.status == "active"
