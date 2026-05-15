"""Tests for session reaper stale detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workflows.session_reaper import reap_stale_sessions


@pytest.mark.asyncio
async def test_session_reaper_uses_event_recency_for_dead_transcript_sync_detection() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result

    await reap_stale_sessions(mock_db, datetime.now(UTC))

    statement = mock_db.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "session_events" in sql
    assert "max(session_events.created_at)" in sql
    assert "sessions.updated_at" in sql


@pytest.mark.asyncio
async def test_session_reaper_does_not_complete_generic_inactive_sessions() -> None:
    mock_db = AsyncMock()
    completion_session = MagicMock(
        id="sess-completion",
        status="active",
        request_source=None,
        provider_metadata={},
    )
    completion_result = MagicMock()
    completion_result.scalars.return_value.all.return_value = [completion_session]
    mock_db.execute.return_value = completion_result

    reaped_completion, reaped_stale = await reap_stale_sessions(mock_db, datetime.now(UTC))

    assert reaped_completion == 0
    assert reaped_stale == 0
    assert completion_session.status == "active"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_reaper_early_reaps_dead_transcript_sync_observer() -> None:
    mock_db = AsyncMock()
    now = datetime.now(UTC)
    transcript_sync_session = MagicMock(
        id="sess-transcript",
        status="active",
        request_source="codex-transcript-sync",
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Transcript sync heartbeat",
                "last_event_type": "heartbeat",
                "last_event_at": (now - timedelta(hours=2)).isoformat(),
                "last_model_activity_at": (now - timedelta(hours=2)).isoformat(),
                "last_heartbeat_at": (now - timedelta(hours=2)).isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 25,
            }
        },
    )
    completion_result = MagicMock()
    completion_result.scalars.return_value.all.return_value = [transcript_sync_session]
    mock_db.execute.return_value = completion_result

    reaped_completion, reaped_stale = await reap_stale_sessions(mock_db, now)

    assert reaped_completion == 0
    assert reaped_stale == 1
    assert transcript_sync_session.status == "completed"
    assert transcript_sync_session.provider_metadata["live_activity"]["phase"] == "completed"
    assert transcript_sync_session.provider_metadata["live_activity"]["summary"] == (
        "Auto-completed by session reaper after 1h dead transcript-sync inactivity"
    )
    assert transcript_sync_session.provider_metadata["live_activity"]["termination_reason"] == (
        "session_reaper_dead_transcript_sync"
    )
    mock_db.commit.assert_awaited_once()
