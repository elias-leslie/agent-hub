"""Tests for stale session cleanup queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.session_cleanup import (
    cleanup_stale_sessions,
    cleanup_superseded_persona_heartbeat_sessions,
    get_stale_session_stats,
)


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_uses_event_recency_not_only_session_row() -> None:
    mock_db = AsyncMock()
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = select_result

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=0))
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


@pytest.mark.asyncio
async def test_cleanup_superseded_persona_heartbeat_sessions_closes_older_active_rows() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 2
    mock_db.execute.return_value = mock_result

    now = datetime.now(UTC)
    active_rows = [
        SimpleNamespace(id="sess-newest", created_at=now - timedelta(minutes=2)),
        SimpleNamespace(id="sess-old-1", created_at=now - timedelta(minutes=10)),
        SimpleNamespace(id="sess-old-2", created_at=now - timedelta(minutes=20)),
    ]

    from app.tasks import session_cleanup as mod

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(mod, "_latest_completed_persona_heartbeat_at", AsyncMock(return_value=now - timedelta(minutes=5)))
        mp.setattr(mod, "_query_active_persona_heartbeat_sessions", AsyncMock(return_value=active_rows))

        cleaned = await cleanup_superseded_persona_heartbeat_sessions(mock_db)

    assert cleaned == 2
    statement = mock_db.execute.await_args.args[0]
    sql = str(statement)
    assert "UPDATE sessions" in sql
    compiled = statement.compile()
    ids = set(compiled.params["id_1"])
    assert ids == {"sess-old-1", "sess-old-2"}


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_runs_superseded_heartbeat_cleanup_first() -> None:
    mock_db = AsyncMock()
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = select_result

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=1))
        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 1


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_updates_ids_returned_by_select() -> None:
    mock_db = AsyncMock()
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = ["sess-1", "sess-2"]
    update_result = MagicMock()
    update_result.rowcount = 2
    mock_db.execute.side_effect = [select_result, update_result]

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_session_timeouts", lambda: {"completion": 10})
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=0))
        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 2
    update_stmt = mock_db.execute.await_args_list[1].args[0]
    compiled = update_stmt.compile()
    assert set(compiled.params["id_1"]) == {"sess-1", "sess-2"}
