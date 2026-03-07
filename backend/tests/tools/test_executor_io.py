"""Focused tests for task lane loading helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_load_task_lane_sessions_matches_external_id_and_branch_prefix() -> None:
    """Lane loading should support explicit task links and older branch-only sessions."""
    from app.services.tools._executor_io import _load_task_lane_sessions

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        await _load_task_lane_sessions("task-42")

    statement = mock_db.execute.await_args.args[0]
    compiled = str(statement)

    assert "sessions.external_id = :external_id_1" in compiled
    assert "sessions.current_branch = :current_branch_1" in compiled
    assert "sessions.current_branch LIKE :current_branch_2" in compiled
