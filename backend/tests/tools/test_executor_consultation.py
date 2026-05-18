"""Tests for executor consultation observability and dispatch helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ownership_inventory import ActiveSpecialistSession, OwnershipOwner
from app.services.tools._executor_consultation import inspect_session, query_sessions
from app.services.tools._executor_dispatch import (
    _ensure_task_lane_context,
)
from app.services.tools._executor_dispatch import (
    parse_specialist_dispatch_request as _parse_specialist_dispatch_request,
)
from app.services.tools._executor_dispatch import (
    project_dispatch_overlap_block_reason as _project_dispatch_overlap_block_reason,
)


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
        current_branch="task-123/main",
        workstream_status="authoritative",
        provider_metadata={"cwd": "/tmp/lanes/task-123"},
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
    assert "branch=task-123/main" in result
    assert "lane=authoritative" in result
    assert "cwd=/tmp/lanes/task-123" in result
    assert "Closed the loop" in result
    assert "codex/gpt-5.4" in result
    assert "codex/codex/gpt-5.4" not in result


@pytest.mark.asyncio
async def test_query_sessions_includes_live_activity_health_phase_and_quiet() -> None:
    """query_sessions should surface live activity so quiet sessions are observable."""
    mock_db = AsyncMock()
    session = SimpleNamespace(
        id="sess-active",
        agent_slug="reviewer",
        project_id="agent-hub",
        provider="claude",
        model="claude-opus-4-6",
        external_id=None,
        current_branch=None,
        workstream_status=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "current_topic": "task:task-123",
                "last_event_type": "thinking",
                "last_model_activity_at": (datetime.now(UTC) - timedelta(seconds=95)).isoformat(),
            }
        },
        status="active",
        created_at=datetime.now(UTC) - timedelta(minutes=3),
        summary_oneliner=None,
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [session]
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await query_sessions(status="active")

    assert "status=active" in result
    assert "health=quiet" in result
    assert "phase=waiting_for_model" in result
    assert "quiet=" in result
    assert "topic=task:task-123" in result
    assert "last=thinking" in result


@pytest.mark.asyncio
async def test_query_sessions_excludes_dead_candidate_active_sessions() -> None:
    """Active session queries should ignore heartbeat-only dead candidates."""
    mock_db = AsyncMock()
    now = datetime.now(UTC)
    live_session = SimpleNamespace(
        id="sess-live",
        agent_slug="reviewer",
        project_id="agent-hub",
        provider="claude",
        model="claude-opus-4-6",
        external_id=None,
        current_branch=None,
        workstream_status=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "last_event_type": "tool_result",
                "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            }
        },
        status="active",
        created_at=now - timedelta(minutes=6),
        summary_oneliner=None,
    )
    dead_session = SimpleNamespace(
        id="sess-dead",
        agent_slug="reviewer",
        project_id="agent-hub",
        provider="codex",
        model="gpt-5.4",
        external_id=None,
        current_branch=None,
        workstream_status=None,
        provider_metadata={
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "last_event_type": "heartbeat",
                "last_event_at": (now - timedelta(minutes=45)).isoformat(),
                "last_model_activity_at": (now - timedelta(minutes=45)).isoformat(),
                "last_heartbeat_at": now.isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            }
        },
        status="active",
        created_at=now - timedelta(minutes=50),
        summary_oneliner=None,
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [live_session, dead_session]
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await query_sessions(status="active")

    assert "sess-live" in result
    assert "sess-dead" not in result


@pytest.mark.asyncio
async def test_inspect_session_returns_summary_and_latest_message() -> None:
    mock_db = AsyncMock()
    session = SimpleNamespace(
        id="sess-1",
        agent_slug="governance-auditor",
        project_id="agent-hub",
        status="completed",
        summary_oneliner="Governance audit found a tool gap",
    )
    assistant_event = SimpleNamespace(
        session_id="sess-1",
        event_type="assistant_message",
        content="VERDICT: action_needed\nRECOMMENDATIONS:\n- type=tool_fix",
        tool_name=None,
        turn=1,
        sequence=4,
    )
    tool_event = SimpleNamespace(
        session_id="sess-1",
        event_type="tool_use",
        content=None,
        tool_name="manage_feedback",
        turn=1,
        sequence=2,
    )
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = session
    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = [assistant_event, tool_event]
    mock_db.execute.side_effect = [session_result, events_result]

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await inspect_session("sess-1")

    assert "Session: sess-1" in result
    assert "Agent: governance-auditor" in result
    assert "Summary: Governance audit found a tool gap" in result
    assert "Recent tools: manage_feedback" in result
    assert "VERDICT: action_needed" in result


@pytest.mark.asyncio
async def test_inspect_session_not_found() -> None:
    mock_db = AsyncMock()
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = session_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    with patch("app.db.async_session", _session):
        result = await inspect_session("missing")

    assert "session 'missing' not found" in result


def test_parse_specialist_dispatch_request_reads_mode_and_task_id() -> None:
    parsed = _parse_specialist_dispatch_request(
        "Mode: task\nTask-ID: task-12345678\nTask: Refactor the overlap guard."
    )

    assert parsed.mode == "task"
    assert parsed.task_id == "task-12345678"


@pytest.mark.asyncio
async def test_ensure_task_lane_context_returns_project_root_post_lease_migration() -> None:
    """Per-task branches were eliminated in the lease migration. The lane
    context now returns (None, project_root, None) for any claimed task —
    branch parsing is gone."""
    details = (
        "CHECKPOINT:task-42\n"
        "  Project: summitflow\n"
        "  Base branch: main\n"
        "  Created: 2026-04-20T22:01:00.948638+00:00 (3m ago)\n"
        "  Claimed by: Elias Leslie\n"
    )

    with (
        patch(
            "app.services.tools._executor_dispatch._run_project_st_command",
            new_callable=AsyncMock,
            return_value=details,
        ) as mock_st,
        patch(
            "app.constants.projects.get_known_roots",
            return_value={"summitflow": "/srv/workspaces/projects/summitflow"},
        ),
    ):
        branch, working_dir, error = await _ensure_task_lane_context("summitflow", "task-42")

    assert branch is None
    assert working_dir == "/srv/workspaces/projects/summitflow"
    assert error is None
    mock_st.assert_awaited_once_with("summitflow", "checkpoints --details task-42")


@pytest.mark.asyncio
async def test_ensure_task_lane_context_blocks_when_project_root_unknown() -> None:
    """Project must have a known root; missing project_id maps to a clear error."""
    with (
        patch(
            "app.services.tools._executor_dispatch._run_project_st_command",
            new_callable=AsyncMock,
            return_value="CHECKPOINT:task-42\n",
        ),
        patch("app.constants.projects.get_known_roots", return_value={}),
    ):
        branch, working_dir, error = await _ensure_task_lane_context("missing", "task-42")

    assert branch is None
    assert working_dir is None
    assert error is not None
    assert "unable to resolve project root" in error


@pytest.mark.asyncio
async def test_project_dispatch_overlap_block_reason_allows_missing_scope_specialist() -> None:
    block = await _project_dispatch_overlap_block_reason(
        project_id="agent-hub",
        agent_slug="debugger",
        mode="campaign",
        task_id=None,
        owners=[],
        specialists=[
            ActiveSpecialistSession(
                session_id="sess-1",
                agent_slug="reviewer",
                project_id="agent-hub",
                parent_session_id=None,
                request_source="persona_wake:dispatch",
                created_at=datetime.now(UTC),
                age_minutes=2,
            )
        ],
    )

    assert block is None


@pytest.mark.asyncio
async def test_project_dispatch_overlap_block_reason_ignores_persona_heartbeat_session() -> None:
    block = await _project_dispatch_overlap_block_reason(
        project_id="agent-hub",
        agent_slug="refactor",
        mode="task",
        task_id="task-141fb0da",
        owners=[],
        specialists=[
            ActiveSpecialistSession(
                session_id="sess-persona",
                agent_slug="persona",
                project_id="agent-hub",
                parent_session_id=None,
                request_source="heartbeat",
                created_at=datetime.now(UTC),
                age_minutes=1,
            )
        ],
    )

    assert block is None


@pytest.mark.asyncio
async def test_project_dispatch_overlap_block_reason_blocks_shared_plumbing_owner() -> None:
    block = await _project_dispatch_overlap_block_reason(
        project_id="agent-hub",
        agent_slug="debugger",
        mode="task",
        task_id="task-12345678",
        owners=[
            OwnershipOwner(
                task_id="task-deadbeef",
                session_id="sess-owner",
                agent_slug="coder",
                branch="task-deadbeef/main",
                working_dir="/tmp/lanes/task-deadbeef",
                session_status="active",
                workstream_status=None,
                workstream_note=None,
                ownership_kind="scoped",
                scope_paths=["backend/alembic/versions/123_add_mode.py"],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                age_minutes=1,
                is_stale=False,
            )
        ],
        specialists=[],
    )

    assert block is not None
    assert "shared-plumbing" in block
    assert "backend/alembic/versions/123_add_mode.py" in block


@pytest.mark.asyncio
async def test_project_dispatch_overlap_block_reason_allows_owner_without_scope_paths() -> None:
    block = await _project_dispatch_overlap_block_reason(
        project_id="agent-hub",
        agent_slug="debugger",
        mode="task",
        task_id="task-12345678",
        owners=[
            OwnershipOwner(
                task_id="task-deadbeef",
                session_id="sess-owner",
                agent_slug="coder",
                branch="task-deadbeef/main",
                working_dir="/tmp/lanes/task-deadbeef",
                session_status="active",
                workstream_status=None,
                workstream_note=None,
                ownership_kind="scoped",
                scope_paths=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                age_minutes=1,
                is_stale=False,
            )
        ],
        specialists=[],
    )

    assert block is None
