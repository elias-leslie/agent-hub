"""Drift map for orchestration surfaces.

Locks current mismatches so follow-up repair can target source truth instead of prompt folklore.
"""

from __future__ import annotations

from app.api.endpoints.workflow import _DEFAULT_STAGE_AGENTS, _DEFAULT_STAGE_PHASES
from app.api.orchestration_models import ParallelTaskRequest, SubagentRequest, WorkflowRequest


def test_workflow_request_is_canonical_stage_surface() -> None:
    request = WorkflowRequest(
        project_id="agent-hub",
        shared_context="Repo: agent-hub",
        clarify={"task": "Clarify scope."},
        execute={
            "task": "Implement fix.",
            "execute_tools": True,
            "max_turns": 6,
            "working_dir": "/srv/workspaces/projects/agent-hub",
            "current_branch": "task-123",
            "include_roles": ["autocode"],
        },
        qa={"task": "Run QA."},
    )

    assert request.clarify is not None
    assert request.execute is not None
    assert request.qa is not None
    assert request.execute.execute_tools is True
    assert request.execute.max_turns == 6
    assert request.execute.working_dir == "/srv/workspaces/projects/agent-hub"
    assert request.execute.current_branch == "task-123"
    assert request.execute.include_roles == ["autocode"]
    assert _DEFAULT_STAGE_AGENTS == {
        "clarify": "chat",
        "plan": "planner",
        "execute": "coder",
        "review": "reviewer",
        "qa": "critic",
    }
    assert _DEFAULT_STAGE_PHASES == {
        "clarify": "planning",
        "plan": "planning",
        "execute": "implementation",
        "review": "review",
        "qa": "review",
    }


def test_subagent_request_exposes_agent_slug_but_generic_endpoint_contract_cannot_use_workflow_fields() -> None:
    request = SubagentRequest(
        task="Implement fix.",
        agent_slug="coder",
        thinking_level="high",
        project_id="agent-hub",
    )

    payload = request.model_dump(exclude_none=True)

    assert payload["agent_slug"] == "coder"
    assert "current_branch" not in SubagentRequest.model_fields
    assert "working_dir" not in SubagentRequest.model_fields
    assert "execute_tools" not in SubagentRequest.model_fields
    assert "include_roles" not in SubagentRequest.model_fields
    assert "use_memory" not in SubagentRequest.model_fields


def test_parallel_request_routes_each_task_through_an_agent_slug() -> None:
    task = ParallelTaskRequest(task="Review diff.", name="review")
    payload = task.model_dump(exclude_none=True)

    assert payload == {
        "task": "Review diff.",
        "name": "review",
        "provider": "gemini",
        "temperature": 1.0,
        "agent_slug": "chat",
    }
    assert "agent_slug" in ParallelTaskRequest.model_fields
    assert "thinking_level" not in ParallelTaskRequest.model_fields
    assert "current_branch" not in ParallelTaskRequest.model_fields
    assert "working_dir" not in ParallelTaskRequest.model_fields
    assert "execute_tools" not in ParallelTaskRequest.model_fields
    assert "include_roles" not in ParallelTaskRequest.model_fields
