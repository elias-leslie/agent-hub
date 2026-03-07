"""Tests for active session continuity queries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.continuity_query import query_active_sessions


@pytest.mark.asyncio
async def test_query_active_sessions_filters_to_real_agents() -> None:
    """Active-session continuity should ignore imported sessions without agent slugs."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await query_active_sessions(mock_db)

    statement = mock_db.execute.await_args.args[0]
    sql = str(statement)
    assert "sessions.agent_slug IS NOT NULL" in sql, f"Expected agent_slug filter in SQL: {sql}"
