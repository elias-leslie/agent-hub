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
)
from app.services.session_ingestion.service import (
    append_normalized_events,
    heartbeat_session,
    upsert_session,
)


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
            "app.services.session_ingestion.service.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion.service.get_max_sequence",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion.service.store_event",
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
async def test_append_normalized_events_single_implicit_event_uses_fast_path() -> None:
    db = AsyncMock()
    session = MagicMock()
    stored_event = MagicMock()
    stored_event.id = "evt-fast"
    stored_event.turn = 4
    stored_event.sequence = 9

    with (
        patch(
            "app.services.session_ingestion.service.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ) as mock_store,
        patch(
            "app.services.session_ingestion.service.get_max_turn",
            new_callable=AsyncMock,
        ) as mock_get_max_turn,
        patch(
            "app.services.session_ingestion.service._load_existing_pairs",
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
    assert mock_store.await_args.kwargs["session"] is session
    mock_get_max_turn.assert_not_awaited()
    mock_load_existing_pairs.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_session_create_sets_timestamps_without_refresh() -> None:
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
    assert session.provider_metadata["live_activity"]["phase"] == "running_tool"
    assert session.provider_metadata["live_activity"]["last_read_path"] == "backend/app/api/sessions.py"
    assert session.updated_at is not None
    assert db.commit.await_count == 1
    db.refresh.assert_not_awaited()
