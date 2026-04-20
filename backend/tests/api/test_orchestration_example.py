"""Tests for the canonical orchestration workflow example."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PATH = REPO_ROOT / "examples" / "orchestration_example.py"


def _load_example_module():
    spec = importlib.util.spec_from_file_location("orchestration_example", EXAMPLE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_workflow_request_payload_matches_canonical_contract() -> None:
    example = _load_example_module()

    payload = example.build_workflow_request_payload(
        project_id="agent-hub",
        working_dir="/tmp/agent-hub",
        current_branch="task-123/main",
    )

    assert payload["project_id"] == "agent-hub"
    assert payload["clarify"]["task"]
    assert payload["plan"]["task"]
    assert payload["review"]["task"]
    assert payload["qa"]["task"]
    assert payload["execute"] == {
        "task": "Implement approved plan in repo using existing orchestration and agent-routing primitives.",
        "execute_tools": True,
        "max_turns": 6,
        "working_dir": "/tmp/agent-hub",
        "current_branch": "task-123/main",
    }


def test_build_workflow_request_payload_omits_branch_when_not_provided() -> None:
    example = _load_example_module()

    payload = example.build_workflow_request_payload(
        project_id="agent-hub",
        working_dir="/tmp/agent-hub",
    )

    assert payload["execute"]["working_dir"] == "/tmp/agent-hub"
    assert "current_branch" not in payload["execute"]
