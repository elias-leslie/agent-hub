"""Tests for session management functionality."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpx import HTTPXMock

from agent_hub import (
    AsyncAgentHubClient,
    Session,
    SessionContext,
    CompletionResponse,
    SessionResponse,
    Message,
)


class TestSession:
    """Tests for Session class."""

    @pytest.mark.asyncio
    async def test_session_complete(self, httpx_mock: HTTPXMock) -> None:
        """Test sending a message through session."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Hello! I'm Claude.",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
                "session_id": "test-session",
                "finish_reason": "end_turn",
                "from_cache": False,
            },
        )

        async with AsyncAgentHubClient() as client:
            session = Session(
                client=client,
                session_id="test-session",
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

            response = await session.complete("Hello!")

        assert response.content == "Hello! I'm Claude."
        assert response.session_id == "test-session"

        # Check local history was tracked
        local_history = await session.get_local_history()
        assert len(local_history) == 2
        assert local_history[0]["role"] == "user"
        assert local_history[0]["content"] == "Hello!"
        assert local_history[1]["role"] == "assistant"
        assert local_history[1]["content"] == "Hello! I'm Claude."

    @pytest.mark.asyncio
    async def test_session_add_message(self) -> None:
        """Test adding messages to local tracking."""
        async with AsyncAgentHubClient() as client:
            session = Session(
                client=client,
                session_id="test-session",
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

            await session.add_message("system", "You are a helpful assistant.")
            await session.add_message("user", "Hello")

            history = await session.get_local_history()
            assert len(history) == 2
            assert history[0]["role"] == "system"
            assert history[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_session_get_history(self, httpx_mock: HTTPXMock) -> None:
        """Test getting history from server."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/test-session",
            method="GET",
            json={
                "id": "test-session",
                "project_id": "test-project",
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
                    },
                    {
                        "id": 2,
                        "role": "assistant",
                        "content": "Hi there!",
                        "tokens": 8,
                        "created_at": "2026-01-06T12:00:01Z",
                    },
                ],
            },
        )

        async with AsyncAgentHubClient() as client:
            session = Session(
                client=client,
                session_id="test-session",
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

            history = await session.get_history()

        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "Hello"
        assert history[1].role == "assistant"
        assert history[1].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_session_refresh(self, httpx_mock: HTTPXMock) -> None:
        """Test refreshing session from server."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/test-session",
            method="GET",
            json={
                "id": "test-session",
                "project_id": "test-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:05:00Z",
                "messages": [],
            },
        )

        async with AsyncAgentHubClient() as client:
            session = Session(
                client=client,
                session_id="test-session",
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

            session_data = await session.refresh()

        assert session_data.id == "test-session"
        assert session_data.status == "active"

    @pytest.mark.asyncio
    async def test_session_close(self, httpx_mock: HTTPXMock) -> None:
        """Test closing/archiving a session."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/test-session",
            method="DELETE",
            status_code=204,
        )

        async with AsyncAgentHubClient() as client:
            session = Session(
                client=client,
                session_id="test-session",
                project_id="test-project",
                provider="claude",
                model="claude-sonnet-4-5",
            )

            await session.close()


class TestSessionContext:
    """Tests for SessionContext (context manager)."""

    @pytest.mark.asyncio
    async def test_session_context_new_session(self, httpx_mock: HTTPXMock) -> None:
        """Test creating a new session via context manager."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions",
            method="POST",
            json={
                "id": "new-session-id",
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [],
            },
        )

        async with AsyncAgentHubClient() as client:
            async with client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
            ) as session:
                assert session.session_id == "new-session-id"
                assert session.project_id == "my-project"
                assert session.model == "claude-sonnet-4-5"

    @pytest.mark.asyncio
    async def test_session_context_resume_session(self, httpx_mock: HTTPXMock) -> None:
        """Test resuming an existing session."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions/existing-session",
            method="GET",
            json={
                "id": "existing-session",
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T10:00:00Z",
                "updated_at": "2026-01-06T11:00:00Z",
                "messages": [
                    {
                        "id": 1,
                        "role": "user",
                        "content": "Previous message",
                        "tokens": 10,
                        "created_at": "2026-01-06T10:00:00Z",
                    }
                ],
            },
        )

        async with AsyncAgentHubClient() as client:
            async with client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
                session_id="existing-session",
            ) as session:
                assert session.session_id == "existing-session"

    @pytest.mark.asyncio
    async def test_session_context_persists_session_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Test that session ID is persisted across requests."""
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions",
            method="POST",
            json={
                "id": "persistent-session",
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [],
            },
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "First response",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                "session_id": "persistent-session",
                "from_cache": False,
            },
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Second response",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "session_id": "persistent-session",
                "from_cache": False,
            },
        )

        async with AsyncAgentHubClient() as client:
            async with client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
            ) as session:
                response1 = await session.complete("Hello")
                response2 = await session.complete("Continue")

                assert response1.session_id == "persistent-session"
                assert response2.session_id == "persistent-session"

        # Verify both requests used the same session_id
        requests = httpx_mock.get_requests()
        complete_requests = [r for r in requests if "/complete" in str(r.url)]
        assert len(complete_requests) == 2
        for req in complete_requests:
            import json
            body = json.loads(req.content)
            assert body["session_id"] == "persistent-session"


class TestSessionStreaming:
    """Tests for streaming within a session."""

    @pytest.mark.asyncio
    async def test_session_stream(self) -> None:
        """Test streaming through session tracks content."""
        ws_messages = [
            '{"type": "content", "content": "Hello"}',
            '{"type": "content", "content": " world"}',
            '{"type": "done", "finish_reason": "end_turn"}',
        ]

        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        mock_websocket.__aiter__ = lambda self: mock_aiter()

        with patch("websockets.connect") as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None

            async with AsyncAgentHubClient() as client:
                session = Session(
                    client=client,
                    session_id="stream-session",
                    project_id="test-project",
                    provider="claude",
                    model="claude-sonnet-4-5",
                )

                chunks = []
                async for chunk in session.stream("Tell me something"):
                    chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"

        # Verify local history was updated
        history = await session.get_local_history()
        assert len(history) == 2
        assert history[0]["content"] == "Tell me something"
        assert history[1]["content"] == "Hello world"


class TestSessionPersistence:
    """Tests for session state persistence across instances."""

    @pytest.mark.asyncio
    async def test_session_state_persists(self, httpx_mock: HTTPXMock) -> None:
        """Test that session state persists across client instances."""
        session_id = "persistent-state-session"

        # First client creates session
        httpx_mock.add_response(
            url="http://localhost:8003/api/sessions",
            method="POST",
            json={
                "id": session_id,
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:00:00Z",
                "messages": [],
            },
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            json={
                "content": "Hi!",
                "model": "claude-sonnet-4-5-20250514",
                "provider": "claude",
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                "session_id": session_id,
                "from_cache": False,
            },
        )

        # Second client retrieves session (register upfront)
        httpx_mock.add_response(
            url=f"http://localhost:8003/api/sessions/{session_id}",
            method="GET",
            json={
                "id": session_id,
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:01:00Z",
                "messages": [
                    {
                        "id": 1,
                        "role": "user",
                        "content": "Hello",
                        "tokens": 5,
                        "created_at": "2026-01-06T12:00:00Z",
                    },
                    {
                        "id": 2,
                        "role": "assistant",
                        "content": "Hi!",
                        "tokens": 3,
                        "created_at": "2026-01-06T12:00:01Z",
                    },
                ],
            },
        )

        # Get session ID from first client
        async with AsyncAgentHubClient() as client1:
            async with client1.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
            ) as session1:
                await session1.complete("Hello")
                assert session1.session_id == session_id

        # Resume from new client instance - uses GET mock registered above
        # Need second GET for get_history() call
        httpx_mock.add_response(
            url=f"http://localhost:8003/api/sessions/{session_id}",
            method="GET",
            json={
                "id": session_id,
                "project_id": "my-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "status": "active",
                "created_at": "2026-01-06T12:00:00Z",
                "updated_at": "2026-01-06T12:01:00Z",
                "messages": [
                    {
                        "id": 1,
                        "role": "user",
                        "content": "Hello",
                        "tokens": 5,
                        "created_at": "2026-01-06T12:00:00Z",
                    },
                    {
                        "id": 2,
                        "role": "assistant",
                        "content": "Hi!",
                        "tokens": 3,
                        "created_at": "2026-01-06T12:00:01Z",
                    },
                ],
            },
        )

        async with AsyncAgentHubClient() as client2:
            async with client2.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
                session_id=session_id,
            ) as session2:
                history = await session2.get_history()
                assert len(history) == 2
                assert history[0].content == "Hello"
                assert history[1].content == "Hi!"
