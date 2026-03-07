"""Tests for executor consultation observability helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools._executor_consultation import query_sessions


@pytest.mark.asyncio
async def test_query_sessions_filters_to_real_agents() -> None:
    """query_sessions should ignore imported sessions without agent slugs."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await query_sessions(status="active")

    assert "(No sessions found" in result
    statement = mock_db.execute.await_args.args[0]
    sql = str(statement)
    assert "sessions.agent_slug IS NOT NULL" in sql


@pytest.mark.asyncio
async def test_query_sessions_includes_external_id_when_present() -> None:
    """query_sessions should include task linkage when a session carries external_id."""
    mock_db = AsyncMock()
    session = SimpleNamespace(
        id="sess-1",
        agent_slug="coder",
        project_id="summitflow",
        provider="codex",
        model="codex/gpt-5.4",
        external_id="task-123",
        status="completed",
        created_at=datetime.now(UTC) - timedelta(minutes=2),
        summary_oneliner="Closed the loop",
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [session]
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await query_sessions(status="completed")

    assert "task=task-123" in result
    assert "Closed the loop" in result
