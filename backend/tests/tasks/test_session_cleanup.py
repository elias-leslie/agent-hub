"""Tests for stale session cleanup queries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.session_cleanup import cleanup_stale_sessions, get_stale_session_stats


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_uses_event_recency_not_only_session_row() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result

    await cleanup_stale_sessions(mock_db)

    statement = mock_db.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "session_events" in sql
    assert "max(session_events.created_at)" in sql
    assert "sessions.updated_at" in sql


@pytest.mark.asyncio
async def test_get_stale_session_stats_uses_event_recency_not_only_session_row() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result

    await get_stale_session_stats(mock_db)

    statement = mock_db.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "session_events" in sql
    assert "max(session_events.created_at)" in sql
    assert "sessions.updated_at" in sql
