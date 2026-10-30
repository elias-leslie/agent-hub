"""Tests for the canonical session ingestion service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
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
    SessionIngestionConflict,
    append_normalized_events,
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)

# Repo root of this checkout, so command-scope inference can verify referenced
# source files exist regardless of where CI clones the repo.
REPO_ROOT = str(Path(__file__).resolve().parents[4])

# After the advisory lock, ingestion checks for an event archive to restore.
NO_ARCHIVE = MagicMock(scalar=lambda: False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_serializes_batches_by_session_id() -> None:
    db = AsyncMock()

    lock_result = MagicMock()
    existing_pairs = MagicMock()
    existing_pairs.all.return_value = []
    db.execute = AsyncMock(side_effect=[lock_result, NO_ARCHIVE, existing_pairs])

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
async def test_append_normalized_events_skips_replayed_native_source_identity() -> None:
    db = AsyncMock()
    pairs = MagicMock()
    pairs.all.return_value = []
    stored = MagicMock(
        turn=1,
        sequence=8,
        event_type="usage",
        role=None,
        content=None,
        tool_name=None,
        call_id=None,
        tool_input=None,
        tool_output=None,
        tokens=None,
        duration_ms=None,
        model_used=None,
        agent_id=None,
        agent_name=None,
        transport=None,
        surface=None,
        chat_id=None,
        message_id=None,
        pane_id=None,
        source_client=None,
        source_event_id="response_usage:resp-1:1",
        source_timestamp=None,
        usage={"scope": "response", "input_tokens": 10},
    )
    source_events = MagicMock()
    source_events.scalars.return_value.all.return_value = [stored]
    db.execute = AsyncMock(side_effect=[MagicMock(), NO_ARCHIVE, pairs, source_events])

    with (
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("app.services.session_ingestion._events.store_event", new_callable=AsyncMock) as store,
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-native",
            request=AppendNormalizedEventsRequest(events=[NormalizedEvent(
                event_type="usage", turn=1, sequence=8,
                source_event_id="response_usage:resp-1:1",
                usage={"scope": "response", "input_tokens": 10},
            )]),
        )

    assert result.events_appended == 0
    assert result.events_skipped == 1
    store.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_rejects_changed_native_source_identity() -> None:
    db = AsyncMock()
    pairs = MagicMock()
    pairs.all.return_value = []
    stored = MagicMock(
        turn=1,
        sequence=8,
        event_type="assistant_message",
        role="assistant",
        content="first content",
        tool_name=None,
        call_id=None,
        tool_input=None,
        tool_output=None,
        tokens=None,
        duration_ms=None,
        model_used=None,
        agent_id=None,
        agent_name=None,
        transport=None,
        surface=None,
        chat_id=None,
        message_id=None,
        pane_id=None,
        source_client=None,
        source_event_id="event_msg:item-1:1",
        source_timestamp=None,
        usage=None,
    )
    source_events = MagicMock()
    source_events.scalars.return_value.all.return_value = [stored]
    db.execute = AsyncMock(side_effect=[MagicMock(), NO_ARCHIVE, pairs, source_events])

    with (
        patch(
            "app.services.session_ingestion._events.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("app.services.session_ingestion._events.store_event", new_callable=AsyncMock) as store,
        pytest.raises(ValueError, match="replayed with different content"),
    ):
        await append_normalized_events(
            db=db,
            session_id="session-native",
            request=AppendNormalizedEventsRequest(events=[NormalizedEvent(
                event_type="assistant_message",
                turn=1,
                sequence=8,
                role="assistant",
                content="changed content",
                source_event_id="event_msg:item-1:1",
            )]),
        )

    store.assert_not_awaited()


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
                ("claude-sonnet-5-5", None),
                ("claude-sonnet-5-5", None),
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
                        model_used="claude-sonnet-5-5",
                    )
                ]
            ),
            session=session,
        )

    assert result is append_result
    assert session.model == "claude-sonnet-5-5"
    assert session.models_used == ["claude-sonnet-5-5"]
    mock_store.assert_awaited_once()
    assert db.commit.await_count == 1


def _transcript_session(session_id: str) -> Session:
    session = Session(
        id=session_id,
        project_id="agent-hub",
        provider="claude",
        model="opus-4-6",
        status="active",
        session_type="claude_code",
        provider_metadata={"transcript_path": f"/tmp/{session_id}.jsonl"},
        models_used=["opus-4-6"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    return session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_does_not_lazy_load_session_expired_by_rollback() -> None:
    """Regression: a duplicate implicit event rolls back and expires the session.

    Reading ``provider_metadata`` afterwards used to issue a sync lazy load
    (``MissingGreenlet`` -> HTTP 500 on POST /api/sessions/{id}/events).
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession
    from sqlalchemy.orm import make_transient_to_detached

    from app.services.event_storage import get_sequencer

    session_id = "session-expired-after-rollback"
    session = _transcript_session(session_id)
    make_transient_to_detached(session)
    unbound = OrmSession()
    unbound.add(session)  # persistent in a session with no bind: any lazy load raises

    fresh = _transcript_session(session_id)
    db = AsyncMock()
    db.rollback = AsyncMock(side_effect=lambda: unbound.expire(session))
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: fresh),
            MagicMock(all=lambda: [("claude-sonnet-5-5", None)]),
        ]
    )

    stored = MagicMock(id="evt-retried", turn=2, sequence=8)
    with (
        patch(
            "app.services.session_ingestion._events.store_event",
            new_callable=AsyncMock,
            side_effect=[IntegrityError("insert", {}, Exception("uq_session_turn_sequence")), stored],
        ) as mock_store,
        patch("app.services.session_ingestion._events.lock_session_event_ingestion", new_callable=AsyncMock),
        patch("app.services.session_ingestion._events.get_max_turn", new_callable=AsyncMock, return_value=2),
        patch("app.services.session_ingestion._events.get_max_sequence", new_callable=AsyncMock, return_value=7),
    ):
        result = await append_normalized_events(
            db=db,
            session_id=session_id,
            request=AppendNormalizedEventsRequest(
                events=[NormalizedEvent(event_type="tool_use", tool_name="Bash")]
            ),
            session=session,
        )

    # The colliding implicit event is retried with DB-derived numbering, not dropped.
    assert (result.events_appended, result.events_skipped) == (1, 0)
    assert result.event_ids == ["evt-retried"]
    retry = mock_store.await_args_list[1].kwargs
    assert (retry["turn"], retry["sequence"], retry["session"]) == (2, 8, None)
    assert get_sequencer().get_turn_sequence(session_id) == (2, 9)
    # The rolled-back instance was never touched again (still fully expired).
    assert "provider_metadata" in sa_inspect(session).expired_attributes
    # Reconciliation re-selected the row with await instead of lazy loading it.
    assert db.execute.await_count == 2
    assert fresh.model == "claude-sonnet-5-5"
    assert fresh.models_used == ["claude-sonnet-5-5"]


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
    db.refresh.assert_awaited_once_with(session, with_for_update=True)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("blank", [None, ""])
async def test_upsert_session_keeps_identity_fields_when_later_upsert_omits_them(blank: str | None) -> None:
    """Regression: a bare re-upsert erased external_id/agent_slug/current_branch."""
    db = AsyncMock()
    session = Session(
        id="session-identity",
        project_id="agent-hub",
        provider="anthropic",
        model="claude/external-tmux",
        status="active",
        session_type="claude_code",
        agent_slug="coder",
        external_id="cc-native-123",
        current_branch="feature/x",
        provider_metadata={},
        models_used=["claude/external-tmux"],
        providers_used=["anthropic"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)

    async def _upsert(**fields: str | None) -> None:
        with (
            patch("app.services.session_ingestion.service._validate_project_id", new_callable=AsyncMock),
            patch(
                "app.services.session_ingestion.service.get_or_create_session",
                new_callable=AsyncMock,
                return_value=(session, True),
            ),
            patch(
                "app.services.session_ingestion.service.resolve_agent",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(provider="anthropic", model="claude/external-tmux"),
            ),
        ):
            await upsert_session(
                db=db,
                request=SessionUpsertRequest(
                    session_id="session-identity",
                    project_id="agent-hub",
                    provider="anthropic",
                    model="claude/external-tmux",
                    session_type="claude_code",
                    **fields,
                ),
            )

    await _upsert(agent_slug=blank, external_id=blank, current_branch=blank)
    assert (session.agent_slug, session.external_id, session.current_branch) == (
        "coder", "cc-native-123", "feature/x",
    )

    await _upsert(agent_slug="reviewer", external_id="cc-native-456", current_branch="main")
    assert (session.agent_slug, session.external_id, session.current_branch) == (
        "reviewer", "cc-native-456", "main",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_rejects_existing_session_project_move() -> None:
    db = AsyncMock()
    existing = Session(
        id="session-existing",
        project_id="aftertimes",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
    )

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            return_value=(existing, True),
        ),
        pytest.raises(SessionIngestionConflict) as exc_info,
    ):
        await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-existing",
                project_id="rootfall",
                provider="codex",
                model="codex/gpt-5.4",
            ),
        )

    assert exc_info.value.code == "session_project_immutable"
    assert existing.project_id == "aftertimes"
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_rejects_self_parent() -> None:
    db = AsyncMock()

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
        pytest.raises(SessionIngestionConflict) as exc_info,
    ):
        await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-child",
                parent_session_id="session-child",
                project_id="aftertimes",
                provider="codex",
                model="codex/gpt-5.4",
            ),
        )

    assert exc_info.value.code == "session_parent_self_reference"
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_rejects_missing_parent() -> None:
    db = AsyncMock()

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            side_effect=[(None, False), (None, False)],
        ),
        pytest.raises(SessionIngestionConflict) as exc_info,
    ):
        await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-child",
                parent_session_id="session-missing",
                project_id="aftertimes",
                provider="codex",
                model="codex/gpt-5.4",
            ),
        )

    assert exc_info.value.code == "session_parent_not_found"
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_rejects_parent_from_another_project() -> None:
    db = AsyncMock()
    parent = Session(
        id="session-parent",
        project_id="rootfall",
        provider="claude",
        model="claude-sonnet-5-5",
        status="active",
        session_type="claude_code",
    )

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            side_effect=[(None, False), (parent, True)],
        ),
        pytest.raises(SessionIngestionConflict) as exc_info,
    ):
        await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-child",
                parent_session_id="session-parent",
                project_id="aftertimes",
                provider="codex",
                model="codex/gpt-5.4",
            ),
        )

    assert exc_info.value.code == "session_parent_project_mismatch"
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_links_existing_parent_in_same_project() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    parent = Session(
        id="session-parent",
        project_id="aftertimes",
        provider="claude",
        model="claude-sonnet-5-5",
        status="active",
        session_type="claude_code",
    )

    with (
        patch(
            "app.services.session_ingestion.service._validate_project_id",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_ingestion.service.get_or_create_session",
            new_callable=AsyncMock,
            side_effect=[(None, False), (parent, True)],
        ),
    ):
        session, result = await upsert_session(
            db=db,
            request=SessionUpsertRequest(
                session_id="session-child",
                parent_session_id="session-parent",
                project_id="aftertimes",
                provider="codex",
                model="codex/gpt-5.4",
            ),
        )

    assert result.created is True
    assert session.parent_session_id == "session-parent"
    db.commit.assert_awaited_once()


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
async def test_heartbeat_session_refreshes_and_locks_before_metadata_update() -> None:
    db = AsyncMock()
    session = Session(
        id="session-heartbeat",
        project_id="agent-hub",
        provider="claude",
        model="claude-sonnet-5-5",
        status="active",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude-sonnet-5-5"],
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
    db.refresh.assert_awaited_once_with(session, with_for_update=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_reconciles_direct_session_models_from_event_evidence() -> None:
    db = AsyncMock()
    session = Session(
        id="session-direct",
        project_id="agent-hub",
        provider="claude",
        model="claude-sonnet-5-5",
        status="active",
        session_type="claude_code",
        provider_metadata={},
        models_used=["claude-opus-4-6", "claude-sonnet-5-5"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    ("claude-sonnet-5-5", None),
                    (None, None),
                    ("claude-sonnet-5-5", None),
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
    assert session.model == "claude-sonnet-5-5"
    assert session.models_used == ["claude-sonnet-5-5"]
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_transcript_events_retains_native_source_health_for_refresh(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"session_meta","payload":{"id":"session-health"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"content":[{"type":"output_text","text":"ready"}]}}\n'
    )
    session = Session(
        id="session-health",
        project_id="neri",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
        provider_metadata={"transcript_path": str(transcript)},
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db = AsyncMock()
    append_result = MagicMock(
        events_appended=1,
        events_skipped=0,
        last_turn=1,
        last_sequence=1,
        event_ids=["event-1"],
    )

    with (
        patch(
            "app.services.session_ingestion.service.append_normalized_events",
            new_callable=AsyncMock,
            return_value=append_result,
        ),
        patch(
            "app.services.session_ingestion.service._reconcile_transcript_session_models",
            new_callable=AsyncMock,
        ),
    ):
        result = await ingest_transcript_events(
            db=db,
            session_id=session.id,
            request=TranscriptIngestRequest(
                provider="codex",
                transcript_path=str(transcript),
            ),
            session=session,
        )

    assert result.source_health.state == "ready"
    assert session.provider_metadata is not None
    retained = session.provider_metadata["transcript_ingestion"]
    assert retained["provider"] == "codex"
    assert retained["transcript_path"] == str(transcript)
    assert retained["checkpoint"] == result.next_checkpoint
    assert retained["source_health"]["state"] == "ready"
    assert db.commit.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_rejects_codex_transcript_from_another_native_session(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "wrong-session.jsonl"
    transcript.write_text(
        '{"type":"session_meta","payload":{"id":"different-session"}}\n'
    )
    session = Session(
        id="expected-session",
        project_id="neri",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        session_type="agent",
        provider_metadata={"transcript_path": str(transcript)},
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)

    with pytest.raises(SessionIngestionConflict) as denied:
        await ingest_transcript_events(
            db=AsyncMock(),
            session_id=session.id,
            request=TranscriptIngestRequest(
                provider="codex",
                transcript_path=str(transcript),
            ),
            session=session,
        )

    assert denied.value.code == "transcript_session_identity_mismatch"


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
        models_used=["claude-haiku-5-5"],
        providers_used=["claude"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: session),
            MagicMock(
                all=lambda: [
                    ("claude-sonnet-5-5", None),
                    ("claude-opus-4-6", "agent-1"),
                    ("claude-sonnet-5-5", None),
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

    assert session.model == "claude-sonnet-5-5"
    assert session.models_used == ["claude-sonnet-5-5", "claude-opus-4-6"]
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
            "repo_root": REPO_ROOT,
            "transcript_path": "/tmp/session-scope.jsonl",
        },
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # Session ingestion advisory lock.
            NO_ARCHIVE,
            MagicMock(
                all=lambda: [
                    (
                        "exec_command",
                        {
                            "cmd": (
                                'st create -t bug '
                                '"Detached rebuilds stayed active while agent-hub-frontend stop timed out '
                                'and was SIGKILLed before restart. Health recovered, but systemctl status '
                                'looked hung until the transient unit disappeared, which made runtime '
                                'verification noisier than it needed to be."'
                            ),
                            "workdir": REPO_ROOT,
                        },
                    ),
                    (
                        "exec_command",
                        {
                            "cmd": "sed -n '1,20p' backend/app/services/session_scope.py",
                            "workdir": REPO_ROOT,
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
            "app.services.session_ingestion.service.validate_native_provenance",
        ),
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
            session=session,
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
            "app.services.session_ingestion.service.validate_native_provenance",
        ),
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
            session=session,
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
