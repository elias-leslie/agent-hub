"""Tests for _executor_io — manage_tasks create with subtasks."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.services.tools._executor_io import _build_plan_json, _handle_create, manage_tasks


class TestBuildPlanJson:
    """Tests for _build_plan_json plan file generation."""

    def test_basic_plan_no_subtasks(self) -> None:
        """Plan without subtasks omits the key."""
        path = _build_plan_json(
            title="Test task",
            objective="Do the thing",
            description=None,
            spirit_anti=None,
            done_when=None,
            labels=None,
            complexity=None,
        )
        with open(path) as f:
            plan = json.load(f)
        assert plan["title"] == "Test task"
        assert plan["objective"] == "Do the thing"
        assert "subtasks" not in plan

    def test_plan_with_subtasks(self) -> None:
        """Plan with subtasks includes them in the JSON."""
        subtasks = [
            {"id": "1.1", "description": "Backend API", "subtask_type": "backend"},
            {
                "id": "1.2",
                "description": "Frontend UI",
                "subtask_type": "frontend",
                "depends_on": ["1.1"],
            },
        ]
        path = _build_plan_json(
            title="Multi-phase feature",
            objective="Build the feature end-to-end",
            description="Full stack implementation",
            spirit_anti=None,
            done_when=["API works", "UI renders"],
            labels="feature,frontend",
            complexity="STANDARD",
            subtasks=subtasks,
        )
        with open(path) as f:
            plan = json.load(f)

        assert plan["title"] == "Multi-phase feature"
        assert plan["subtasks"] == subtasks
        assert len(plan["subtasks"]) == 2
        assert plan["subtasks"][0]["subtask_type"] == "backend"
        assert plan["subtasks"][1]["depends_on"] == ["1.1"]
        assert plan["done_when"] == ["API works", "UI renders"]
        assert plan["labels"] == ["feature", "frontend"]

    def test_plan_subtasks_without_type(self) -> None:
        """Subtasks without subtask_type are still valid (type is optional)."""
        subtasks = [
            {"id": "1.1", "description": "Do something"},
        ]
        path = _build_plan_json(
            title="Simple task",
            objective="Accomplish goal",
            description=None,
            spirit_anti=None,
            done_when=None,
            labels=None,
            complexity=None,
            subtasks=subtasks,
        )
        with open(path) as f:
            plan = json.load(f)
        assert plan["subtasks"] == subtasks
        assert "subtask_type" not in plan["subtasks"][0]

    def test_empty_subtasks_list_omitted(self) -> None:
        """Empty subtasks list is treated as falsy and omitted."""
        path = _build_plan_json(
            title="No subtasks",
            objective="Simple objective",
            description=None,
            spirit_anti=None,
            done_when=None,
            labels=None,
            complexity=None,
            subtasks=[],
        )
        with open(path) as f:
            plan = json.load(f)
        assert "subtasks" not in plan


class TestHandleCreateWithSubtasks:
    """Tests for _handle_create passing subtasks to plan creation."""

    @pytest.mark.asyncio
    async def test_subtasks_trigger_plan_path(self) -> None:
        """Passing subtasks (even without objective) uses plan-based creation."""
        bash_fn = AsyncMock(return_value="Task #42 created")
        subtasks = [
            {"id": "1.1", "description": "Backend work", "subtask_type": "backend"},
        ]
        result = await _handle_create(
            bash_fn=bash_fn,
            title="Test task",
            description=None,
            priority=2,
            task_type="task",
            labels=None,
            project_id="summitflow",
            objective=None,
            spirit_anti=None,
            done_when=None,
            complexity=None,
            subtasks=subtasks,
        )
        assert result == "Task #42 created"
        # Should have called bash with st -P summitflow create --plan <tmpfile>
        call_args = bash_fn.call_args[0][0]
        assert "create --plan" in call_args
        assert "-P summitflow" in call_args

    @pytest.mark.asyncio
    async def test_subtasks_in_plan_file(self) -> None:
        """The plan JSON file written contains the subtasks."""
        written_cmd = None

        async def capture_bash(cmd: str) -> str:
            nonlocal written_cmd
            written_cmd = cmd
            return "Created"

        subtasks = [
            {"id": "1.1", "description": "DB migration", "subtask_type": "database"},
            {"id": "1.2", "description": "API endpoint", "subtask_type": "backend", "depends_on": ["1.1"]},
        ]
        await _handle_create(
            bash_fn=capture_bash,
            title="Add endpoint",
            description=None,
            priority=2,
            task_type="feature",
            labels=None,
            project_id=None,
            objective="New endpoint works",
            spirit_anti=None,
            done_when=["Endpoint returns 200"],
            complexity="STANDARD",
            subtasks=subtasks,
        )
        # Extract the plan file path from the command
        assert written_cmd is not None
        assert "--plan" in written_cmd
        # The path is after --plan, possibly quoted
        parts = written_cmd.split("--plan ")
        plan_path = parts[1].strip().strip("'\"")

        with open(plan_path) as f:
            plan = json.load(f)

        assert plan["subtasks"] == subtasks
        assert plan["objective"] == "New endpoint works"


class TestManageTasksCreateSubtasks:
    """Tests for manage_tasks action=create with subtasks parameter."""

    @pytest.mark.asyncio
    async def test_create_with_subtasks(self) -> None:
        """manage_tasks passes subtasks through to _handle_create."""
        bash_fn = AsyncMock(return_value="Task created")
        subtasks = [
            {"id": "1.1", "description": "Test subtask", "subtask_type": "test"},
        ]
        result = await manage_tasks(
            bash_fn=bash_fn,
            action="create",
            title="Subtask test",
            objective="Test objective",
            subtasks=subtasks,
        )
        assert "Task created" in result
        call_args = bash_fn.call_args[0][0]
        assert "--plan" in call_args

    @pytest.mark.asyncio
    async def test_create_without_subtasks_basic_path(self) -> None:
        """Without subtasks or objective, uses basic CLI creation."""
        bash_fn = AsyncMock(return_value="Task created")
        result = await manage_tasks(
            bash_fn=bash_fn,
            action="create",
            title="Simple task",
        )
        assert "Task created" in result
        call_args = bash_fn.call_args[0][0]
        assert "--plan" not in call_args
        assert "create" in call_args
