"""Tests for Agent Hub client."""

from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from pytest_httpx import HTTPXMock

from agent_hub import (
    AgentHubClient,
    AsyncAgentHubClient,
    AuthenticationError,
    CompletionResponse,
    MessageInput,
    RateLimitError,
    ServerError,
    SessionResponse,
    ValidationError,
)


class TestAgentHubClient:
    """Tests for sync client."""

    def test_init_defaults(self) -> None:
        """Test client initialization with defaults."""
        client = AgentHubClient()
        assert client.base_url == "http://localhost:8003"
        assert client.api_key is None
        assert client.timeout == 120.0

    def test_init_custom(self) -> None:
        """Test client initialization with custom values."""
        client = AgentHubClient(
            base_url="http://custom:9000/",
            api_key="test-key",
            timeout=60.0,
        )
        assert client.base_url == "http://custom:9000"
        assert client.api_key == "test-key"
        assert client.timeout == 60.0

    def test_context_manager(self) -> None:
        """Test client as context manager."""
        with AgentHubClient() as client:
            assert client is not None
        assert client._client is None

    def test_complete_success(self, httpx_mock: HTTPXMock) -> None:
        """Test successful completion."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Hello! How can I help?",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "total_tokens": 18,
                },
                "session_id": "test-session",
                "finish_reason": "end_turn",
                "from_cache": False,
            },
        )

        with AgentHubClient() as client:
            response = client.complete(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hello!"}],
            )

        assert response.content == "Hello! How can I help?"
        assert response.model == "claude-sonnet-4-5-20250514"
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 8

    def test_complete_with_message_input(self, httpx_mock: HTTPXMock) -> None:
        """Test completion with MessageInput objects."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Response",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                "session_id": "test",
                "from_cache": False,
            },
        )

        with AgentHubClient() as client:
            response = client.complete(
                model="claude-sonnet-4-5",
                messages=[MessageInput(role="user", content="Test")],
            )

        assert response.content == "Response"

    def test_complete_401_error(self, httpx_mock: HTTPXMock) -> None:
        """Test 401 authentication error."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            status_code=401,
            json={"detail": "Invalid API key"},
        )

        with AgentHubClient() as client:
            with pytest.raises(AuthenticationError) as exc_info:
                client.complete(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello!"}],
                )

        assert exc_info.value.status_code == 401
        assert "Authentication failed" in str(exc_info.value)

    def test_complete_429_rate_limit(self, httpx_mock: HTTPXMock) -> None:
        """Test 429 rate limit error."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            status_code=429,
            json={"detail": "Rate limit exceeded"},
            headers={"Retry-After": "60"},
        )

        with AgentHubClient() as client:
            with pytest.raises(RateLimitError) as exc_info:
                client.complete(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello!"}],
                )

        assert exc_info.value.retry_after == 60.0

    def test_complete_422_validation_error(self, httpx_mock: HTTPXMock) -> None:
        """Test 422 validation error."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            status_code=422,
            json={"detail": "Invalid model"},
        )

        with AgentHubClient() as client:
            with pytest.raises(ValidationError) as exc_info:
                client.complete(
                    model="invalid",
                    messages=[{"role": "user", "content": "Hello!"}],
                )

        assert exc_info.value.status_code == 422

    def test_complete_500_server_error(self, httpx_mock: HTTPXMock) -> None:
        """Test 500 server error."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            status_code=500,
            json={"detail": "Internal error"},
        )

        with AgentHubClient() as client:
            with pytest.raises(ServerError) as exc_info:
                client.complete(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello!"}],
                )

        assert exc_info.value.status_code == 500

    def test_create_session(self, httpx_mock: HTTPXMock) -> None:
        """Test session creation."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions",
            method="POST",
            json={
                "id": "new-session-id",
                "project_id": "test-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [],
            },
        )

        with AgentHubClient() as client:
            session = client.create_session(
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

        assert session.id == "new-session-id"
        assert session.status == "active"

    def test_get_session(self, httpx_mock: HTTPXMock) -> None:
        """Test getting session by ID."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/test-session",
            method="GET",
            json={
                "id": "test-session",
                "project_id": "proj",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [
                    {
                        "id": 1,
                        "role": "user",
                        "content": "Hello",
                        "tokens": 5,
                        "created_at": "2026-01-06T12:00:00Z",
                    }
                ],
            },
        )

        with AgentHubClient() as client:
            session = client.get_session("test-session")

        assert session.id == "test-session"
        assert len(session.messages) == 1
        assert session.messages[0].content == "Hello"

    def test_list_sessions(self, httpx_mock: HTTPXMock) -> None:
        """Test listing sessions."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions?page=1&page_size=20&project_id=proj",
            method="GET",
            json={
                "sessions": [
                    {
                        "id": "session-1",
                        "project_id": "proj",
                        "provider": "claude",
                        "model": "claude-sonnet-4-5",
                        "status": "active",
                        "message_count": 5,
                        "created_at": "2026-01-06T12:00:00Z",
                        "updated_at": "2026-01-06T12:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            },
        )

        with AgentHubClient() as client:
            result = client.list_sessions(project_id="proj")

        assert len(result.sessions) == 1
        assert result.sessions[0].id == "session-1"
        assert result.total == 1

    def test_delete_session(self, httpx_mock: HTTPXMock) -> None:
        """Test deleting session."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/test-session",
            method="DELETE",
            status_code=204,
        )

        with AgentHubClient() as client:
            client.delete_session("test-session")

    def test_api_key_header(self, httpx_mock: HTTPXMock) -> None:
        """Test API key is included in headers."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Response",
                "model": "claude-sonnet-4-5",
                "provider": "claude",
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                "session_id": "test",
                "from_cache": False,
            },
        )

        with AgentHubClient(api_key="sk-test-key") as client:
            client.complete(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Test"}],
            )

        request = httpx_mock.get_request()
        assert request is not None
        assert request.headers["authorization"] == "Bearer sk-test-key"


class TestAsyncAgentHubClient:
    """Tests for async client."""

    @pytest.mark.asyncio
    async def test_init_defaults(self) -> None:
        """Test async client initialization with defaults."""
        client = AsyncAgentHubClient()
        assert client.base_url == "http://localhost:8003"
        assert client.api_key is None

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async client as context manager."""
        async with AsyncAgentHubClient() as client:
            assert client is not None
        assert client._client is None

    @pytest.mark.asyncio
    async def test_complete_success(self, httpx_mock: HTTPXMock) -> None:
        """Test successful async completion."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Async response!",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "session_id": "async-session",
                "finish_reason": "end_turn",
                "from_cache": False,
            },
        )

        async with AsyncAgentHubClient() as client:
            response = await client.complete(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hello!"}],
            )

        assert response.content == "Async response!"

    @pytest.mark.asyncio
    async def test_complete_with_session_id(self, httpx_mock: HTTPXMock) -> None:
        """Test completion with session ID."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Continued conversation",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                "session_id": "existing-session",
                "from_cache": False,
            },
        )

        async with AsyncAgentHubClient() as client:
            response = await client.complete(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Continue"}],
                session_id="existing-session",
            )

        assert response.session_id == "existing-session"

        request = httpx_mock.get_request()
        assert request is not None
        import json
        body = json.loads(request.content)
        assert body["session_id"] == "existing-session"

    @pytest.mark.asyncio
    async def test_create_session(self, httpx_mock: HTTPXMock) -> None:
        """Test async session creation."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions",
            method="POST",
            json={
                "id": "async-session",
                "project_id": "async-project",
                "provider": "gemini",
                "model": "gemini-3-flash",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [],
            },
        )

        async with AsyncAgentHubClient() as client:
            session = await client.create_session(
                project_id="async-project",
                provider="gemini",
                model="gemini-3-flash",
            )

        assert session.id == "async-session"
        assert session.provider == "gemini"

    @pytest.mark.asyncio
    async def test_cancel_stream(self, httpx_mock: HTTPXMock) -> None:
        """Test cancelling a stream."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/streaming-session/cancel",
            method="POST",
            json={
                "session_id": "streaming-session",
                "cancelled": True,
                "input_tokens": 100,
                "output_tokens": 50,
                "message": "Stream cancelled",
            },
        )

        async with AsyncAgentHubClient() as client:
            result = await client.cancel_stream("streaming-session")

        assert result["cancelled"] is True
        assert result["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_error_handling(self, httpx_mock: HTTPXMock) -> None:
        """Test error handling in async client."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            status_code=429,
            json={"detail": "Too many requests"},
            headers={"Retry-After": "30"},
        )

        async with AsyncAgentHubClient() as client:
            with pytest.raises(RateLimitError) as exc_info:
                await client.complete(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello!"}],
                )

        assert exc_info.value.retry_after == 30.0
