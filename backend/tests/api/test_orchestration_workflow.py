"""Tests for the canonical orchestration workflow API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.api.complete.schemas import CompletionResponse
from app.api.complete.usage_schemas import UsageInfo
from tests.conftest import APITestClient


def _completion(stage: str, *, index: int, agent_slug: str) -> CompletionResponse:
    input_tokens = 10 + index
    output_tokens = 5 + index
    return CompletionResponse(
        content=f"{stage} output",
        model="codex/gpt-5.4",
        provider="codex",
        usage=UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        session_id=f"sess-{stage}",
        agent_used=agent_slug,
        model_used="codex/gpt-5.4",
        fallback_used=False,
        memory_facts_injected=index,
        cited_uuids=[f"{stage}-citation"],
    )


def test_workflow_endpoint_runs_stages_with_defaults_and_prior_outputs(
    api_client: APITestClient,
) -> None:
    captured_requests = []
    stage_order = ["clarify", "plan", "execute", "review", "qa"]

    async def fake_orchestrate(request, http_request, skip_cache, db):
        del http_request, skip_cache, db
        captured_requests.append(request)
        stage = stage_order[len(captured_requests) - 1]
        return _completion(stage, index=len(captured_requests), agent_slug=request.agent_slug)

    with patch(
        "app.api.endpoints.workflow.orchestrate_completion",
        new_callable=AsyncMock,
    ) as mock_orchestrate:
        mock_orchestrate.side_effect = fake_orchestrate

        response = api_client.post(
            "/api/orchestration/workflow",
            json={
                "project_id": "agent-hub",
                "parent_session_id": "persona-root",
                "clarify": {"task": "Ask the missing questions."},
                "plan": {"task": "Create an execution-ready plan."},
                "execute": {
                    "task": "Implement the approved plan.",
                    "execute_tools": True,
                    "max_turns": 4,
                },
                "review": {"task": "Review the implementation for defects."},
                "qa": {"task": "Run final QA over the workflow."},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["final_output"] == "qa output"
    assert payload["total_input_tokens"] == 65
    assert payload["total_output_tokens"] == 40
    assert [stage["stage"] for stage in payload["stages"]] == stage_order
    assert [stage["agent_used"] for stage in payload["stages"]] == [
        "chat",
        "planner",
        "coder",
        "reviewer",
        "critic",
    ]

    assert [request.agent_slug for request in captured_requests] == [
        "chat",
        "planner",
        "coder",
        "reviewer",
        "critic",
    ]
    assert [request.phase for request in captured_requests] == [
        "planning",
        "planning",
        "implementation",
        "review",
        "review",
    ]
    assert all(request.parent_session_id == "persona-root" for request in captured_requests)
    assert "Workflow stage: clarify" in captured_requests[0].messages[0].content
    assert "clarify output" in captured_requests[1].messages[0].content
    assert "clarify output" in captured_requests[2].messages[0].content
    assert "plan output" in captured_requests[2].messages[0].content
    assert "execute output" in captured_requests[3].messages[0].content
    assert "review output" in captured_requests[4].messages[0].content
    assert captured_requests[2].execute_tools is True
    assert captured_requests[2].max_turns == 4


def test_workflow_endpoint_honors_stage_overrides(api_client: APITestClient) -> None:
    captured_requests = []

    async def fake_orchestrate(request, http_request, skip_cache, db):
        del http_request, skip_cache, db
        captured_requests.append(request)
        return _completion("execute", index=1, agent_slug=request.agent_slug)

    with patch(
        "app.api.endpoints.workflow.orchestrate_completion",
        new_callable=AsyncMock,
    ) as mock_orchestrate:
        mock_orchestrate.side_effect = fake_orchestrate

        response = api_client.post(
            "/api/orchestration/workflow",
            json={
                "project_id": "agent-hub",
                "execute": {
                    "task": "Diagnose and fix the failing worker path.",
                    "agent_slug": "debugger",
                    "task_type": "bug-fix",
                    "phase": "implementation",
                    "use_memory": False,
                    "execute_tools": True,
                    "max_turns": 6,
                    "working_dir": "/tmp/task-123",
                    "current_branch": "task-123",
                    "thinking_level": "high",
                    "disable_agent_fallbacks": True,
                    "include_roles": ["system", "autocode"],
                    "response_format": {"type": "json_object"},
                },
            },
        )

    assert response.status_code == 200
    request = captured_requests[0]
    assert request.agent_slug == "debugger"
    assert request.task_type == "bug-fix"
    assert request.phase == "implementation"
    assert request.use_memory is False
    assert request.execute_tools is True
    assert request.max_turns == 6
    assert request.working_dir == "/tmp/task-123"
    assert request.current_branch == "task-123"
    assert request.thinking_level == "high"
    assert request.disable_agent_fallbacks is True
    assert request.include_roles == ["system", "autocode"]
    assert request.response_format is not None
    assert request.response_format.type == "json_object"


def test_workflow_endpoint_requires_at_least_one_stage(api_client: APITestClient) -> None:
    response = api_client.post(
        "/api/orchestration/workflow",
        json={"project_id": "agent-hub"},
    )

    assert response.status_code == 422
    assert "At least one workflow stage" in response.text
