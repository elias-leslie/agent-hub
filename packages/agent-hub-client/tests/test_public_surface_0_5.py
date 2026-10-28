"""Public SDK surface added in 0.5.0 so callers never reach into private transport."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AgentHubClient, AsyncAgentHubClient
from agent_hub._completion import build_completion_payload

BASE = "http://localhost:8003"
DONE = (
    'data: {"type":"content","content":"Hi"}\n\n'
    'data: {"type":"done","finish_reason":"stop","model":"codex/gpt-6.1-sol","provider":"codex",'
    '"session_id":"s1","agent_used":"chat","model_used":"codex/gpt-6.1-sol","fallback_used":false,'
    '"cost_usd":0.001,"thinking_tokens":3}\n\n'
)


def test_catalog_agents_prompt_and_health_are_public(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/models", json={"models": [], "providers": {}})
    httpx_mock.add_response(url=f"{BASE}/api/agents?active_only=true&limit=500&offset=0", json={"agents": []})
    httpx_mock.add_response(url=f"{BASE}/api/prompts/a%2Fb", json={"slug": "a/b"})
    httpx_mock.add_response(url=f"{BASE}/health", json={"status": "ok"})
    with AgentHubClient(client_id="c", request_source="r") as client:
        assert client.list_models() == {"models": [], "providers": {}}
        assert client.list_agents() == {"agents": []}
        assert client.get_prompt("a/b") == {"slug": "a/b"}
        assert client.health() == {"status": "ok"}
    for request in httpx_mock.get_requests():
        assert request.headers["X-Client-Id"] == "c"
        assert request.headers["X-Tool-Name"].startswith("sdk.")


@pytest.mark.asyncio
async def test_stream_done_carries_routing_evidence(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/complete", method="POST", content=DONE.encode())
    async with AsyncAgentHubClient() as client:
        chunks = [c async for c in client.stream_sse([{"role": "user", "content": "x"}], project_id="p", agent_slug="chat")]
    done = chunks[-1]
    assert done.type == "done"
    assert (done.fallback_used, done.agent_used, done.model_used) == (False, "chat", "codex/gpt-6.1-sol")
    assert done.cost_usd == 0.001 and done.thinking_tokens == 3


def test_sync_stream_matches_async(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/complete", method="POST", content=DONE.encode())
    with AgentHubClient() as client:
        chunks = list(client.stream_sse(
            [{"role": "user", "content": "x"}], project_id="p", agent_slug="chat", skip_cache=True, read_only=True,
        ))
    assert [c.type for c in chunks] == ["content", "done"]
    assert chunks[-1].fallback_used is False
    request = httpx_mock.get_requests()[0]
    assert request.headers["X-Skip-Cache"] == "true"
    body = json.loads(request.content)
    assert body["stream"] is True and body["read_only"] is True and "skip_cache" not in body


def test_payload_sends_only_fields_the_server_accepts() -> None:
    payload = build_completion_payload(
        [{"role": "user", "content": "x"}], "p", agent_slug="chat",
        parent_session_id="parent", source_metadata={"surface": "cli"}, work_context={"mode": "general"},
    )
    assert payload["parent_session_id"] == "parent"
    assert payload["source_metadata"] == {"surface": "cli"}
    assert payload["work_context"] == {"mode": "general"}
    assert not {"purpose", "routing_config", "resume_session_id", "skip_cache"} & set(payload)


def test_session_events_are_public(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/sessions/s1/events?page=1&page_size=50&event_type=tool_use", json={"events": []})
    httpx_mock.add_response(url=f"{BASE}/api/sessions/s1/events", method="POST", json={"id": 1})
    with AgentHubClient() as client:
        assert client.list_session_events("s1", event_type="tool_use", page_size=50) == {"events": []}
        assert client.append_session_event("s1", {"event_type": "lifecycle", "content": "x"}) == {"id": 1}


@pytest.mark.asyncio
async def test_automation_owner_calls_require_and_send_the_internal_secret(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/automations/profiles?project_id=jobs&limit=100", json={"items": [{"id": 1}]})
    httpx_mock.add_response(url=f"{BASE}/api/automations/runs/r1/complete", method="POST", json={"ok": True})
    async with AsyncAgentHubClient() as client:
        assert await client.list_automation_profiles("jobs", internal_secret="s") == [{"id": 1}]
        assert await client.complete_automation_run("r1", {"status": "succeeded"}, internal_secret="s") == {"ok": True}
        with pytest.raises(ValueError):
            await client.list_automation_profiles("jobs", internal_secret="")
    assert all(r.headers["X-Agent-Hub-Internal"] == "s" for r in httpx_mock.get_requests())


@pytest.mark.asyncio
async def test_model_selection_sdk_sends_only_metadata(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/models/selection-policy", json={"version": 2, "task_types": ["visual_reasoning"]})
    httpx_mock.add_response(url=f"{BASE}/api/models/select", method="POST", json={"model": "codex/gpt-6.1-terra", "apply": False})
    async with AsyncAgentHubClient(client_id="c", request_source="r") as client:
        assert (await client.model_selection_policy())["task_types"] == ["visual_reasoning"]
        result = await client.select_model("visual_reasoning", mode="shadow", assigned_model="codex/gpt-6.1-sol")
    assert result["apply"] is False
    assert json.loads(httpx_mock.get_requests()[1].content) == {"task_type": "visual_reasoning", "mode": "shadow", "assigned_model": "codex/gpt-6.1-sol"}
