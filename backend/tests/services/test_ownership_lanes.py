"""Focused tests for shared ownership lane normalization."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.ownership_lanes import (
    OwnershipOwner,
    collapse_active_workstream_rows,
    collapse_ownership_owners,
    infer_task_id,
    prioritize_scope_paths,
)


def _owner(**overrides: object) -> OwnershipOwner:
    now = datetime(2026, 3, 7, 20, 30, tzinfo=UTC)
    payload: dict[str, object] = {
        "task_id": "task-a961e3b9",
        "session_id": "sess-1",
        "agent_slug": "refactor",
        "branch": "task-a961e3b9/main",
        "working_dir": "/tmp/lanes/task-a961e3b9",
        "session_status": "active",
        "workstream_status": None,
        "workstream_note": None,
        "ownership_kind": "scoped",
        "scope_paths": ["backend/app/a.py"],
        "updated_at": now,
        "created_at": now,
        "age_minutes": 2,
        "is_stale": False,
    }
    payload.update(overrides)
    return OwnershipOwner(**payload)


class TestCollapseOwnershipOwners:
    def test_collapses_multiple_sessions_on_same_task_branch_and_checkout(self) -> None:
        owners = [
            _owner(session_id="sess-new", scope_paths=["backend/app/a.py"], age_minutes=2),
            _owner(
                session_id="sess-old",
                scope_paths=["backend/app/b.py"],
                age_minutes=8,
                updated_at=datetime(2026, 3, 7, 20, 24, tzinfo=UTC),
            ),
        ]

        collapsed = collapse_ownership_owners(owners)

        assert len(collapsed) == 1
        assert collapsed[0].session_id == "sess-new"
        assert collapsed[0].scope_paths == ["backend/app/a.py", "backend/app/b.py"]
        assert collapsed[0].age_minutes == 2

    def test_prefers_scoped_owner_over_unscoped_for_same_lane(self) -> None:
        owners = [
            _owner(
                session_id="sess-unscoped",
                ownership_kind="unscoped",
                scope_paths=[],
                updated_at=datetime(2026, 3, 7, 20, 28, tzinfo=UTC),
                age_minutes=4,
            ),
            _owner(
                session_id="sess-scoped",
                ownership_kind="scoped",
                scope_paths=["backend/app/live.py"],
                updated_at=datetime(2026, 3, 7, 20, 27, tzinfo=UTC),
                age_minutes=5,
            ),
        ]

        collapsed = collapse_ownership_owners(owners)

        assert len(collapsed) == 1
        assert collapsed[0].session_id == "sess-scoped"
        assert collapsed[0].scope_paths == ["backend/app/live.py"]

    def test_preserves_distinct_lanes_when_branch_or_checkout_differs(self) -> None:
        owners = [
            _owner(session_id="sess-main", branch="task-a961e3b9/main"),
            _owner(
                session_id="sess-follow-up",
                branch="task-a961e3b9/follow-up",
                working_dir="/tmp/lanes/task-a961e3b9-follow-up",
            ),
        ]

        collapsed = collapse_ownership_owners(owners)

        assert len(collapsed) == 2
        assert {owner.branch for owner in collapsed} == {
            "task-a961e3b9/main",
            "task-a961e3b9/follow-up",
        }


def test_infer_task_id_recovers_from_lane_path_suffix() -> None:
    assert infer_task_id(None, None, "/tmp/lanes/task-a961e3b9-follow-up") == "task-a961e3b9"


def test_prioritize_scope_paths_prefers_declared_and_writes_before_reads() -> None:
    assert prioritize_scope_paths(
        ["backend/app/services/ownership_inventory.py"],
        ["backend/app/services/session_scope.py"],
        [".coverage", "backend/app/services/session_scope.py"],
    ) == [
        "backend/app/services/ownership_inventory.py",
        "backend/app/services/session_scope.py",
        ".coverage",
    ]


class TestCollapseActiveWorkstreamRows:
    def test_collapses_duplicate_active_rows_for_same_lane(self) -> None:
        rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-a961e3b9",
                "current_branch": "task-a961e3b9/main",
                "working_dir": "/tmp/lanes/task-a961e3b9",
                "status": "active",
                "updated_at": datetime(2026, 3, 7, 20, 28, tzinfo=UTC),
                "age_minutes": 2,
            },
            {
                "session_id": "sess-2",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-a961e3b9",
                "current_branch": "task-a961e3b9/main",
                "working_dir": "/tmp/lanes/task-a961e3b9",
                "status": "active",
                "updated_at": datetime(2026, 3, 7, 20, 20, tzinfo=UTC),
                "age_minutes": 10,
            },
        ]

        collapsed = collapse_active_workstream_rows(rows)

        assert len(collapsed) == 1
        assert collapsed[0]["session_id"] == "sess-1"
        assert collapsed[0]["age_minutes"] == 2

    def test_preserves_distinct_active_rows_for_different_branches(self) -> None:
        rows = [
            {
                "session_id": "sess-main",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/main",
                "working_dir": "/tmp/lanes/task-777-main",
                "status": "active",
                "updated_at": datetime(2026, 3, 7, 20, 28, tzinfo=UTC),
                "age_minutes": 2,
            },
            {
                "session_id": "sess-follow-up",
                "agent_slug": "debugger",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/follow-up",
                "working_dir": "/tmp/lanes/task-777-follow-up",
                "status": "active",
                "updated_at": datetime(2026, 3, 7, 20, 27, tzinfo=UTC),
                "age_minutes": 3,
            },
        ]

        collapsed = collapse_active_workstream_rows(rows)

        assert len(collapsed) == 2

    def test_uses_working_dir_to_infer_task_id_for_path_only_lane(self) -> None:
        rows = [
            {
                "session_id": "sess-path",
                "agent_slug": None,
                "project_id": "agent-hub",
                "external_id": None,
                "current_branch": None,
                "working_dir": "/tmp/lanes/task-a961e3b9-follow-up",
                "status": "active",
                "updated_at": datetime(2026, 3, 7, 20, 28, tzinfo=UTC),
                "age_minutes": 2,
            }
        ]

        collapsed = collapse_active_workstream_rows(rows)

        assert len(collapsed) == 1
        assert collapsed[0]["external_id"] == "task-a961e3b9"
