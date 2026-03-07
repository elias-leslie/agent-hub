"""Tests for executor consultation observability helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
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
