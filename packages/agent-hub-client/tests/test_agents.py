import pytest

from agent_hub import AgentHubClient, AsyncAgentHubClient, ServerError


def test_metadata_uses_canonical_client_identity(httpx_mock):
    httpx_mock.add_response(url="http://localhost:8003/api/agents/chat", json={"slug": "chat"})
    with AgentHubClient(client_id="project-client", request_source="project") as client:
        assert client.get_agent("chat") == {"slug": "chat"}
    request = httpx_mock.get_request()
    assert request.headers["X-Client-Id"] == "project-client"
    assert request.headers["X-Request-Source"] == "project"
    assert request.headers["X-Tool-Name"] == "sdk.get_agent"


@pytest.mark.asyncio
async def test_preview_preserves_project_scope_and_reports_failure(httpx_mock):
    httpx_mock.add_response(url="http://localhost:8003/api/agents/chat/preview?project_id=neri", json={"canonical_context": {"status": "ok"}})
    httpx_mock.add_response(url="http://localhost:8003/api/agents/chat", status_code=503)
    async with AsyncAgentHubClient(client_id="project-client") as client:
        result = await client.preview_agent("chat", project_id="neri")
        assert result["canonical_context"]["status"] == "ok"
        with pytest.raises(ServerError):
            await client.get_agent("chat")
