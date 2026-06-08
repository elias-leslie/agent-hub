"""Focused tests for ownership inventory live-lane selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ownership_inventory import (
    query_project_active_specialists,
    query_project_ownership,
)

# Repo root of this checkout, so command-scope inference can verify referenced
# source files exist regardless of where CI clones the repo.
REPO_ROOT = str(Path(__file__).resolve().parents[3])


@pytest.mark.asyncio
async def test_query_project_ownership_includes_claimed_task_with_external_id_only() -> None:
    """A claimed task checkpoint should appear even before any Agent Hub session events exist."""
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
        provider_metadata={"cwd": "/repo/.checkpoints/task-96cf4007"},
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    owner = owners[0]
    assert owner.task_id == "task-96cf4007"
    assert owner.session_id == "sess-claim"
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].task_id == "task-d0cf84cb"
    assert owners[0].ownership_kind == "unscoped"
    assert owners[0].scope_confidence == "unknown"


@pytest.mark.asyncio
async def test_query_project_ownership_includes_repo_root_only_claude_lane() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-claude-lane",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=12),
        updated_at=now - timedelta(minutes=11),
        agent_slug=None,
        external_id=None,
        current_branch=None,
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={"repo_root": "/srv/workspaces/projects/agent-hub/task-b5008fb6"},
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].task_id == "task-b5008fb6"
    assert owners[0].working_dir == "/srv/workspaces/projects/agent-hub/task-b5008fb6"


@pytest.mark.asyncio
async def test_query_project_ownership_skips_stale_unscoped_repo_root_session() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-root-stale",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=50),
        updated_at=now - timedelta(minutes=45),
        agent_slug=None,
        external_id=None,
        current_branch="main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
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
            },
        },
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert owners == []


@pytest.mark.asyncio
async def test_query_project_ownership_keeps_active_unscoped_repo_root_session() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-root-live",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=8),
        updated_at=now - timedelta(minutes=2),
        agent_slug=None,
        external_id=None,
        current_branch="main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Waiting for model after Read",
                "last_event_type": "tool_result",
                "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            },
        },
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].session_id == "sess-root-live"
    assert owners[0].branch == "main"
    assert owners[0].scope_confidence == "unknown"


@pytest.mark.asyncio
async def test_query_project_ownership_derives_scope_from_exec_command_and_apply_patch_events() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-root-scoped",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=8),
        updated_at=now - timedelta(minutes=2),
        agent_slug=None,
        external_id=None,
        current_branch="main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={
            "repo_root": REPO_ROOT,
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Waiting for model after exec_command",
                "last_event_type": "tool_result",
                "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                "outstanding_tool_calls": 0,
                "tool_calls_count": 4,
            },
        },
    )
    exec_event = SimpleNamespace(
        tool_name="exec_command",
        tool_input={
            "cmd": "sed -n '1,20p' backend/app/services/session_scope.py",
            "workdir": REPO_ROOT,
        },
    )
    patch_event = SimpleNamespace(
        tool_name="apply_patch",
        tool_input={
            "input": (
                "*** Begin Patch\n"
                "*** Update File: backend/app/services/ownership_inventory.py\n"
                "@@\n"
                "*** End Patch\n"
            )
        },
    )

    db = AsyncMock()

    with (
        patch(
            "app.services.ownership_inventory._fetch_candidate_sessions",
            new=AsyncMock(return_value=[session]),
        ),
        patch(
            "app.services.ownership_inventory._fetch_scope_events",
            new=AsyncMock(return_value={session.id: [exec_event, patch_event]}),
        ),
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].observed_read_paths == ["backend/app/services/session_scope.py"]
    assert owners[0].observed_write_paths == ["backend/app/services/ownership_inventory.py"]
    assert owners[0].ownership_kind == "scoped"
    assert owners[0].scope_confidence == "observed_write"


@pytest.mark.asyncio
async def test_fetch_candidate_sessions_broadens_candidates_with_session_type_fallback() -> None:
    from app.services.ownership_inventory import _fetch_candidate_sessions

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    await _fetch_candidate_sessions(mock_db, "agent-hub")

    compiled = str(mock_db.execute.await_args.args[0])
    assert "sessions.session_type IN" in compiled
    assert "sessions.agent_slug IS NOT NULL" in compiled
    assert "sessions.external_id IS NOT NULL" in compiled
    assert "sessions.current_branch IS NOT NULL" in compiled


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
        provider_metadata={"cwd": "/repo/.checkpoints/task-a2178df4"},
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
async def test_query_project_ownership_skips_unscoped_persona_heartbeat_even_with_task_lane_metadata() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-persona-heartbeat",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=1),
        agent_slug="persona",
        request_source="heartbeat",
        external_id="task-269134f1",
        current_branch="task-269134f1/main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=[],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence=None,
        provider_metadata={"cwd": "/repo/.checkpoints/task-269134f1"},
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert owners == []


@pytest.mark.asyncio
async def test_query_project_ownership_upgrades_unknown_scope_confidence_from_declared_paths() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-upgrade-confidence",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=1),
        agent_slug="refactor",
        external_id="task-1a2b3c4d",
        current_branch="task-1a2b3c4d/main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=["backend/app/services/ownership_inventory.py"],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence="unknown",
        provider_metadata={"cwd": "/repo/.checkpoints/task-1a2b3c4d"},
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].scope_confidence == "declared"


@pytest.mark.asyncio
async def test_query_project_ownership_keeps_scoped_persona_heartbeat_lane() -> None:
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id="sess-persona-lane",
        project_id="agent-hub",
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=1),
        agent_slug="persona",
        request_source="heartbeat",
        external_id="task-269134f1",
        current_branch="task-269134f1/main",
        status="active",
        workstream_status=None,
        workstream_note=None,
        declared_scope_paths=["frontend/src/app/persona/components/workspace-cards.tsx"],
        observed_read_paths=[],
        observed_write_paths=[],
        scope_confidence="declared",
        provider_metadata={"cwd": "/repo/.checkpoints/task-269134f1"},
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
    ):
        owners = await query_project_ownership(db, "agent-hub")

    assert len(owners) == 1
    assert owners[0].task_id == "task-269134f1"
    assert owners[0].ownership_kind == "scoped"


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
