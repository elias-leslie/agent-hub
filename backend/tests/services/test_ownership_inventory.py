"""Focused tests for ownership inventory live-lane selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ownership_inventory import query_project_ownership


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
