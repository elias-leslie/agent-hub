import json
from pathlib import Path
from unittest.mock import AsyncMock, call

import pytest

from app.services.tools._executor_io_tasks import (
    _build_plan_json,
    _cleanup_dispatch_block_reason,
)


@pytest.mark.asyncio
async def test_cleanup_dispatch_block_reason_ignores_reconciled_review_residue() -> None:
    mock_bash = AsyncMock(
        side_effect=[
            (
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=3 dirty=3 orphan=0 prunable=0\n"
                "agent-hub checkpoints:3 dirty:3 orphan:0 prunable:0 "
                "tasks:task-ff895807,task-40ec1a3d review:task-ff895807,task-40ec1a3d,task-2caf5811"
            ),
            (
                "OWNERSHIP[3]\n"
                "- agent-hub | task-ff895807 | idle=12m | authoritative,superseded\n"
                "- agent-hub | task-40ec1a3d | idle=9m | authoritative,superseded\n"
                "- agent-hub | task-2caf5811 | idle=2m | authoritative,superseded"
            ),
        ]
    )

    block_reason, cleanup_status = await _cleanup_dispatch_block_reason(mock_bash, "agent-hub")

    assert block_reason is None
    assert cleanup_status is not None and "review:task-ff895807" in cleanup_status
    assert mock_bash.await_args_list == [
        call("st -P agent-hub cleanup status"),
        call("st -P agent-hub sessions ownership"),
    ]


@pytest.mark.asyncio
async def test_cleanup_dispatch_block_reason_blocks_live_review_residue() -> None:
    mock_bash = AsyncMock(
        side_effect=[
            (
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=1 orphan=0 prunable=0\n"
                "agent-hub checkpoints:1 dirty:1 orphan:0 prunable:0 review:task-live1234"
            ),
            (
                "OWNERSHIP[1]\n"
                "- agent-hub | task-live1234 | idle=3m | authoritative"
            ),
        ]
    )

    block_reason, cleanup_status = await _cleanup_dispatch_block_reason(mock_bash, "agent-hub")

    assert block_reason is not None
    assert "Dispatch blocked" in block_reason
    assert "task-live1234" in block_reason
    assert cleanup_status is not None


def test_build_plan_json_adds_default_steps_for_subtasks_without_steps() -> None:
    plan_path = Path(
        _build_plan_json(
            title="Fix blocker",
            description="Make the unblock task execution-ready.",
            priority=2,
            task_type="task",
            done_when=["Dispatch succeeds"],
            labels="dispatch,cleanup",
            complexity="STANDARD",
            subtasks=[
                {"id": "1.1", "description": "Localize the cleanup truth mismatch"},
                {"id": "1.2", "description": "Patch the gate", "steps": []},
            ],
        )
    )
    try:
        payload = json.loads(plan_path.read_text())
    finally:
        plan_path.unlink(missing_ok=True)

    assert payload["subtasks"][0]["steps"] == ["Localize the cleanup truth mismatch"]
    assert payload["subtasks"][1]["steps"] == ["Patch the gate"]


def test_build_plan_json_preserves_structured_steps_and_rich_context() -> None:
    plan_path = Path(
        _build_plan_json(
            title="Preserve plan fidelity",
            description="Keep the richer task shape intact.",
            priority=1,
            task_type="feature",
            done_when=["Rich metadata survives import"],
            labels="planning,persona",
            complexity="STANDARD",
            objective="Preserve plan metadata end to end.",
            constraints=["Keep legacy callers working."],
            spirit_anti="No duplicate schema.",
            testing_strategy="Run the focused tool tests and inspect the imported task context.",
            context={
                "files_to_modify": ["backend/app/services/tools/_executor_io_tasks.py"],
                "files_to_create": ["backend/tests/tools/test_executor_io_tasks.py"],
                "risks": ["Schema drift between Agent Hub and SummitFlow."],
                "references": [
                    {"title": "Plan schema", "url": "https://github.com/elias-leslie/summitflow/schemas/plan.json"},
                    {"title": "", "url": "https://invalid.example.com"}
                ],
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "pending",
                    "summary": "Control-plane schema touch."
                },
                "unsupported": ["ignored"]
            },
            subtasks=[
                {
                    "id": "1.1",
                    "phase": "backend",
                    "description": "Preserve structured steps",
                    "subtask_type": "backend",
                    "depends_on": ["0.1"],
                    "unexpected": "drop me",
                    "steps": [
                        {
                            "description": "Carry step metadata through the plan builder.",
                            "spec": {"verify_command": "dt pytest backend/tests/tools/test_executor_io_tasks.py"},
                            "extra": "ignored"
                        }
                    ]
                }
            ],
        )
    )
    try:
        payload = json.loads(plan_path.read_text())
    finally:
        plan_path.unlink(missing_ok=True)

    assert payload["task_type"] == "feature"
    assert payload["priority"] == 1
    assert payload["objective"] == "Preserve plan metadata end to end."
    assert payload["constraints"] == ["Keep legacy callers working."]
    assert payload["spirit_anti"] == "No duplicate schema."
    assert payload["testing_strategy"] == "Run the focused tool tests and inspect the imported task context."
    assert payload["context"] == {
        "files_to_modify": ["backend/app/services/tools/_executor_io_tasks.py"],
        "files_to_create": ["backend/tests/tools/test_executor_io_tasks.py"],
        "risks": ["Schema drift between Agent Hub and SummitFlow."],
        "references": [{"title": "Plan schema", "url": "https://github.com/elias-leslie/summitflow/schemas/plan.json"}],
        "second_opinion": {
            "required": True,
            "stage": "task_shape",
            "status": "pending",
            "summary": "Control-plane schema touch."
        }
    }
    assert payload["subtasks"][0]["phase"] == "backend"
    assert payload["subtasks"][0]["depends_on"] == ["0.1"]
    assert "unexpected" not in payload["subtasks"][0]
    assert payload["subtasks"][0]["steps"] == [
        {
            "description": "Carry step metadata through the plan builder.",
            "spec": {"verify_command": "dt pytest backend/tests/tools/test_executor_io_tasks.py"}
        }
    ]
