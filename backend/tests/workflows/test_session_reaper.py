"""Tests for session reaper stale detection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workflows.session_reaper import reap_stale_sessions


@pytest.mark.asyncio
async def test_session_reaper_uses_event_recency_for_stale_completion_detection() -> None:
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
async def test_session_reaper_uses_event_recency_for_global_stale_detection() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result

    await reap_stale_sessions(mock_db, datetime.now(UTC))

    assert len(mock_db.execute.await_args_list) >= 2, "Expected at least 2 execute calls"
    statement = mock_db.execute.await_args_list[1].args[0]
    sql = str(statement)
    assert "session_events" in sql
    assert "max(session_events.created_at)" in sql
    assert "sessions.updated_at" in sql
