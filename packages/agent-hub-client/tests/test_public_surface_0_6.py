"""Control-plane reads added in 0.6.0 so consumers stop calling Agent Hub with raw HTTP."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AgentHubClient, AsyncAgentHubClient

BASE = "http://localhost:8003"
SESSION = {
    "id": "s1", "project_id": "p", "provider": "codex", "model": "m", "status": "active",
    "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z", "message_count": 0,
    "external_id": "task-1", "current_branch": "main", "fallback_used": False,
    "live_activity": {"lifecycle_state": "working", "health": "ok"},
    "declared_scope_paths": ["backend/"],
}


def test_session_filters_and_fields_survive(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/api/sessions?page=1&page_size=100&project_id=p&status=active&agent_slug=coder"
        "&parent_session_id=s0&external_id=task-1&session_type=agent",
        json={"sessions": [SESSION], "total": 1, "page": 1, "page_size": 100},
    )
    with AgentHubClient() as client:
        result = client.list_sessions(
            "p", "active", page_size=100, agent_slug="coder", parent_session_id="s0",
            external_id="task-1", session_type="agent",
        )
    item = result.sessions[0]
    assert (item.external_id, item.current_branch, item.fallback_used) == ("task-1", "main", False)
    assert item.live_activity == {"lifecycle_state": "working", "health": "ok"}
    # A field the SDK does not declare is kept for pass-through callers.
    assert item.model_dump()["declared_scope_paths"] == ["backend/"]


def test_coding_agent_filter_and_project_reads(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/api/agents?active_only=true&limit=500&offset=0&is_coding_agent=true", json={"agents": []},
    )
    httpx_mock.add_response(url=f"{BASE}/api/projects/a%2Fb/execution-permission", json={"allowed": True})
    httpx_mock.add_response(url=f"{BASE}/api/ownership/projects/p/live", json={"active_owners": []})
    with AgentHubClient() as client:
        assert client.list_agents(is_coding_agent=True) == {"agents": []}
        assert client.get_execution_permission("a/b") == {"allowed": True}
        assert client.get_project_ownership("p") == {"active_owners": []}


@pytest.mark.asyncio
async def test_async_client_matches(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/projects/p/execution-permission", json={"allowed": False})
    httpx_mock.add_response(url=f"{BASE}/api/ownership/projects/p/live", json={"active_owners": []})
    httpx_mock.add_response(
        url=f"{BASE}/api/sessions?page=1&page_size=20&external_id=task-1",
        json={"sessions": [SESSION], "total": 1, "page": 1, "page_size": 20},
    )
    async with AsyncAgentHubClient() as client:
        assert await client.get_execution_permission("p") == {"allowed": False}
        assert await client.get_project_ownership("p") == {"active_owners": []}
        assert (await client.list_sessions(external_id="task-1")).sessions[0].external_id == "task-1"
