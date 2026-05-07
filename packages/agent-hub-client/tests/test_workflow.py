"""Tests for the canonical workflow client helpers."""

import json

import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AgentHubClient, AsyncAgentHubClient


def _workflow_response() -> dict[str, object]:
    return {
        "status": "completed",
        "final_output": "qa output",
        "total_input_tokens": 30,
        "total_output_tokens": 12,
        "stages": [
            {
                "stage": "clarify",
                "agent_used": "chat",
                "content": "clarify output",
                "model": "served-model",
                "provider": "codex",
                "session_id": "sess-clarify",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
            },
            {
                "stage": "qa",
                "agent_used": "critic",
                "content": "qa output",
                "model": "served-model",
                "provider": "codex",
                "session_id": "sess-qa",
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 8,
                    "total_tokens": 28,
                },
            },
        ],
    }


def test_sync_workflow_posts_canonical_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8003/api/orchestration/workflow",
        method="POST",
        json=_workflow_response(),
    )

    with AgentHubClient() as client:
        response = client.workflow(
            project_id="agent-hub",
            shared_context="Repo: agent-hub",
            clarify={"task": "Clarify scope."},
            execute={"task": "Implement the plan.", "execute_tools": True},
            qa={"task": "Run final QA."},
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body == {
        "project_id": "agent-hub",
        "shared_context": "Repo: agent-hub",
        "clarify": {"task": "Clarify scope."},
        "execute": {"task": "Implement the plan.", "execute_tools": True},
        "qa": {"task": "Run final QA."},
    }
    assert request.headers["x-tool-name"] == "sdk.workflow"
    assert response["status"] == "completed"
    assert response["final_output"] == "qa output"


@pytest.mark.asyncio
async def test_async_workflow_posts_canonical_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8003/api/orchestration/workflow",
        method="POST",
        json=_workflow_response(),
    )

    async with AsyncAgentHubClient() as client:
        response = await client.workflow(
            project_id="agent-hub",
            trace_id="task-123",
            plan={"task": "Create the plan."},
            review={"task": "Review the implementation."},
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body == {
        "project_id": "agent-hub",
        "trace_id": "task-123",
        "plan": {"task": "Create the plan."},
        "review": {"task": "Review the implementation."},
    }
    assert request.headers["x-tool-name"] == "sdk.workflow"
    assert response["stages"][0]["stage"] == "clarify"
