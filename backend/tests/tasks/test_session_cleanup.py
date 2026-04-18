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
        mp.setattr(mod, "query_project_ownership", AsyncMock(return_value=[]))
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        await cleanup_stale_sessions(mock_db)

    statement = mock_db.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "SELECT sessions.id" in sql or "FROM sessions" in sql
    assert "sessions.status = :status_1" in sql


@pytest.mark.asyncio
async def test_get_stale_session_stats_uses_event_recency_not_only_session_row() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "query_project_ownership", AsyncMock(return_value=[]))
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
    await get_stale_session_stats(mock_db)

    statement = mock_db.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "SELECT sessions.id" in sql or "FROM sessions" in sql
    assert "sessions.status = :status_1" in sql


@pytest.mark.asyncio
async def test_cleanup_superseded_persona_heartbeat_sessions_closes_older_active_rows() -> None:
    mock_db = AsyncMock()

    now = datetime.now(UTC)
    active_rows = [
        SimpleNamespace(id="sess-newest", created_at=now - timedelta(minutes=2)),
        SimpleNamespace(id="sess-old-1", created_at=now - timedelta(minutes=10)),
        SimpleNamespace(id="sess-old-2", created_at=now - timedelta(minutes=20)),
    ]
    session_one = MagicMock(status="active", provider_metadata={})
    session_two = MagicMock(status="active", provider_metadata={})
    fetch_result = MagicMock()
    fetch_result.scalars.return_value.all.return_value = [session_one, session_two]
    mock_db.execute.return_value = fetch_result

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
    assert "SELECT sessions.id" in sql or "FROM sessions" in sql
    compiled = statement.compile()
    ids = set(compiled.params["id_1"])
    assert ids == {"sess-old-1", "sess-old-2"}
    assert session_one.status == "completed"
    assert session_two.status == "completed"
    assert session_one.provider_metadata["live_activity"]["phase"] == "completed"
    assert session_one.provider_metadata["live_activity"]["status"] == "completed"
    assert session_one.provider_metadata["live_activity"]["summary"] == (
        "Superseded by newer persona heartbeat"
    )


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_runs_superseded_heartbeat_cleanup_first() -> None:
    mock_db = AsyncMock()
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = select_result

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=1))
        mp.setattr(mod, "query_project_ownership", AsyncMock(return_value=[]))
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 1


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_only_reaps_sessions_marked_reapable() -> None:
    mock_db = AsyncMock()
    active_sessions = MagicMock()
    session_one = MagicMock(status="active", provider_metadata={})
    session_one.id = "sess-1"
    session_one.project_id = "agent-hub"
    session_two = MagicMock(status="active", provider_metadata={})
    session_two.id = "sess-2"
    session_two.project_id = "agent-hub"
    active_sessions.scalars.return_value.all.return_value = [session_one, session_two]
    mock_db.execute.return_value = active_sessions

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=0))
        mp.setattr(
            mod,
            "query_project_ownership",
            AsyncMock(return_value=[]),
        )
        mp.setattr(
            mod,
            "query_project_active_specialists",
            AsyncMock(return_value=[]),
        )
        mp.setattr(
            mod,
            "build_live_activity_response",
            MagicMock(side_effect=[
                {"reapable": True, "reapable_reason": "heartbeat_only+no_lane"},
                {"reapable": False},
            ]),
        )
        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 1
    assert session_one.status == "completed"
    assert session_two.status == "active"
    assert session_one.provider_metadata["live_activity"]["phase"] == "completed"
    assert session_one.provider_metadata["live_activity"]["status"] == "completed"
    assert session_one.provider_metadata["live_activity"]["summary"] == "Auto-reaped stale session"
    assert session_one.provider_metadata["live_activity"]["termination_reason"] == "heartbeat_only+no_lane"


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_does_not_reap_owner_lane_sessions() -> None:
    mock_db = AsyncMock()
    active_sessions = MagicMock()
    session_one = MagicMock(status="active", provider_metadata={})
    session_one.id = "sess-1"
    session_one.project_id = "agent-hub"
    active_sessions.scalars.return_value.all.return_value = [session_one]
    mock_db.execute.return_value = active_sessions

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=0))
        mp.setattr(
            mod,
            "query_project_ownership",
            AsyncMock(return_value=[SimpleNamespace(session_id="sess-1", branch="task-123/main")]),
        )
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        build_live_activity = MagicMock(return_value={"reapable": False})
        mp.setattr(mod, "build_live_activity_response", build_live_activity)

        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 0
    assert session_one.status == "active"
    assert build_live_activity.call_args.kwargs["has_owner_lane"] is True
    assert build_live_activity.call_args.kwargs["has_specialist_lane"] is False


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_reaps_ghost_owner_lane_sessions(tmp_path) -> None:
    mock_db = AsyncMock()
    active_sessions = MagicMock()
    session_one = MagicMock(status="active", provider_metadata={})
    session_one.id = "sess-1"
    session_one.project_id = "agent-hub"
    active_sessions.scalars.return_value.all.return_value = [session_one]
    mock_db.execute.return_value = active_sessions

    ghost_path = tmp_path / "ghost-lane"

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "cleanup_superseded_persona_heartbeat_sessions", AsyncMock(return_value=0))
        mp.setattr(
            mod,
            "query_project_ownership",
            AsyncMock(
                return_value=[
                    SimpleNamespace(
                        session_id="sess-1",
                        branch=None,
                        working_dir=str(ghost_path),
                    )
                ]
            ),
        )
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        build_live_activity = MagicMock(
            return_value={"reapable": True, "reapable_reason": "heartbeat_only+no_lane"}
        )
        mp.setattr(mod, "build_live_activity_response", build_live_activity)

        cleaned = await cleanup_stale_sessions(mock_db)

    assert cleaned == 1
    assert session_one.status == "completed"
    assert build_live_activity.call_args.kwargs["has_owner_lane"] is False


@pytest.mark.asyncio
async def test_get_stale_session_stats_ignores_ghost_owner_lane_blockers(tmp_path) -> None:
    mock_db = AsyncMock()
    active_sessions = MagicMock()
    session_one = MagicMock(status="active", provider_metadata={}, session_type="agent")
    session_one.id = "sess-1"
    session_one.project_id = "agent-hub"
    active_sessions.scalars.return_value.all.return_value = [session_one]
    mock_db.execute.return_value = active_sessions

    ghost_path = tmp_path / "ghost-lane"

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            mod,
            "query_project_ownership",
            AsyncMock(
                return_value=[
                    SimpleNamespace(
                        session_id="sess-1",
                        branch=None,
                        working_dir=str(ghost_path),
                    )
                ]
            ),
        )
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        build_live_activity = MagicMock(return_value={"reapable": True})
        mp.setattr(mod, "build_live_activity_response", build_live_activity)

        stats = await get_stale_session_stats(mock_db)

    assert stats == {"agent": 1}
    assert build_live_activity.call_args.kwargs["has_owner_lane"] is False


@pytest.mark.asyncio
async def test_get_stale_session_stats_counts_only_reapable_sessions() -> None:
    mock_db = AsyncMock()
    active_sessions = MagicMock()
    session_one = MagicMock(status="active", provider_metadata={}, session_type="completion")
    session_one.id = "sess-1"
    session_one.project_id = "agent-hub"
    session_two = MagicMock(status="active", provider_metadata={}, session_type="agent")
    session_two.id = "sess-2"
    session_two.project_id = "agent-hub"
    active_sessions.scalars.return_value.all.return_value = [session_one, session_two]
    mock_db.execute.return_value = active_sessions

    from app.tasks import session_cleanup as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "query_project_ownership", AsyncMock(return_value=[]))
        mp.setattr(mod, "query_project_active_specialists", AsyncMock(return_value=[]))
        mp.setattr(
            mod,
            "build_live_activity_response",
            MagicMock(side_effect=[{"reapable": True}, {"reapable": False}]),
        )
        stats = await get_stale_session_stats(mock_db)

    assert stats == {"completion": 1}
