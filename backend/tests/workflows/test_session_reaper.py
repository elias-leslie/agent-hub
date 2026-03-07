"""Tests for session reaper stale detection."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.session_reaper import session_reaper_task


def _mock_async_session(mock_db):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


@pytest.mark.asyncio
async def test_session_reaper_uses_event_recency_for_stale_completion_detection() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result
    ctx = SimpleNamespace(log=MagicMock())

    with patch("app.db.async_session", _mock_async_session(mock_db)):
        await session_reaper_task(SimpleNamespace(), ctx)

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
    ctx = SimpleNamespace(log=MagicMock())

    with patch("app.db.async_session", _mock_async_session(mock_db)):
        await session_reaper_task(SimpleNamespace(), ctx)

    statement = mock_db.execute.await_args_list[1].args[0]
    sql = str(statement)
    assert "session_events" in sql
    assert "max(session_events.created_at)" in sql
    assert "sessions.updated_at" in sql
