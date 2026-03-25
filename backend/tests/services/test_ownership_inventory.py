"""Focused tests for ownership inventory live-lane selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)


@pytest.mark.asyncio
async def test_query_project_ownership_includes_claimed_task_with_external_id_only() -> None:
    """A claimed task lane should appear even before any Agent Hub session events exist."""
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-claim",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=1),
        agent_slug="coder",
        external_id="task-96cf4007",
        current_branch=None,
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={"cwd": "/repo/.worktrees/task-96cf4007"},
    )

    db = AsyncMock()

    with (
        patch(
            "app.services.ownership_inventory._fetch_candidate_sessions",
            new=AsyncMock(return_value=[session]),
        ),
        patch(
            "app.services.ownership_inventory._fetch_scope_events",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.ownership_inventory._is_worktree", return_value=True),
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    owner = owners[0]
    assert owner.task_id == "task-96cf4007"
    assert owner.session_id == "sess-claim"
    assert owner.is_worktree is True
    assert owner.ownership_kind == "unscoped"
    assert owner.scope_confidence == "unknown"


@pytest.mark.asyncio
async def test_query_project_ownership_marks_external_id_only_task_lanes_as_unscoped() -> None:
    """Task-linked claims with no branch or write events should still surface as owner lanes."""
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-specialist",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=1),
        agent_slug="reviewer",
        external_id="task-d0cf84cb",
        current_branch=None,
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={"cwd": "/repo"},
    )

    db = AsyncMock()

    with (
        patch(
            "app.services.ownership_inventory._fetch_candidate_sessions",
            new=AsyncMock(return_value=[session]),
        ),
        patch(
            "app.services.ownership_inventory._fetch_scope_events",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.ownership_inventory._is_worktree", return_value=False),
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].task_id == "task-d0cf84cb"
    assert owners[0].ownership_kind == "unscoped"
    assert owners[0].scope_confidence == "unknown"


@pytest.mark.asyncio
async def test_query_project_ownership_marks_idle_completion_lane_stale_after_30_minutes() -> None:
    session = SimpleNamespace(
        id="sess-stale",
        project_id="agent-hub",
        created_at=datetime.now(UTC) - timedelta(minutes=40),
        updated_at=datetime.now(UTC) - timedelta(minutes=31),
        agent_slug="refactor",
        external_id="task-a2178df4",
        current_branch="task-a2178df4/main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=["backend/app/services/ownership_inventory.py"],
        observed_read_paths=["backend/app/services/session_live_activity.py"],
        observed_write_paths=["backend/app/services/ownership_inventory.py"],
        scope_confidence="declared",
        provider_metadata={"cwd": "/repo/.worktrees/task-a2178df4"},
    )

    db = AsyncMock()

    with (
        patch(
            "app.services.ownership_inventory._fetch_candidate_sessions",
            new=AsyncMock(return_value=[session]),
        ),
        patch(
            "app.services.ownership_inventory._fetch_scope_events",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.ownership_inventory._is_worktree", return_value=True),
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].task_id == "task-a2178df4"
    assert owners[0].is_stale is True
    assert owners[0].ownership_kind == "stale"
    assert owners[0].declared_scope_paths == ["backend/app/services/ownership_inventory.py"]
    assert owners[0].observed_read_paths == ["backend/app/services/session_live_activity.py"]
    assert owners[0].observed_write_paths == ["backend/app/services/ownership_inventory.py"]


@pytest.mark.asyncio
async def test_query_project_active_specialists_excludes_dead_candidate_sessions() -> None:
    now = datetime.now(UTC)
    persona_session = SimpleNamespace(
        id="sess-persona",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=3),
        updated_at=now - timedelta(minutes=1),
        agent_slug="persona",
        parent_session_id=None,
        request_source="heartbeat",
        status="active",
        external_id=None,
        current_branch=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Heartbeat running",
                "last_event_type": "heartbeat",
                "last_event_at": now.isoformat(),
                "last_model_activity_at": now.isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 1,
            }
        },
    )
    live_session = SimpleNamespace(
        id="sess-live",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=8),
        updated_at=now - timedelta(minutes=1),
        agent_slug="reviewer",
        parent_session_id="parent-live",
        request_source="dispatch",
        status="active",
        external_id=None,
        current_branch=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Waiting for model after Read",
                "last_event_type": "tool_result",
                "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 1,
            }
        },
    )
    dead_candidate = SimpleNamespace(
        id="sess-dead",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=50),
        updated_at=now - timedelta(minutes=45),
        agent_slug="reviewer",
        parent_session_id="parent-dead",
        request_source="dispatch",
        status="active",
        external_id=None,
        current_branch=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Transcript sync heartbeat",
                "last_event_type": "heartbeat",
                "last_event_at": (now - timedelta(minutes=45)).isoformat(),
                "last_model_activity_at": (now - timedelta(hours=2)).isoformat(),
                "last_heartbeat_at": now.isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            }
        },
    )

    db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [persona_session, live_session, dead_candidate]
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    specialists = await query_project_active_specialists(db, "agent-hub")

    assert [specialist.session_id for specialist in specialists] == ["sess-live"]
