"""Tests for /complete endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    RateLimitError,
    ProviderError,
)
from app.main import app


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


class TestCompleteEndpoint:
    """Tests for POST /api/complete."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        with patch("app.api.complete.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hello there!",
                    model="claude-sonnet-4-5-20250514",
                    provider="claude",
                    input_tokens=10,
                    output_tokens=5,
                    finish_reason="end_turn",
                )
            )
            mock.return_value = adapter
            yield mock

    @pytest.fixture
    def mock_gemini_adapter(self):
        """Mock GeminiAdapter."""
        with patch("app.api.complete.GeminiAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hi from Gemini!",
                    model="gemini-2.0-flash",
                    provider="gemini",
                    input_tokens=8,
                    output_tokens=4,
                    finish_reason="STOP",
                )
            )
            mock.return_value = adapter
            yield mock

    def test_complete_claude_success(self, client, mock_claude_adapter):
        """Test successful Claude completion."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hello there!"
        assert data["provider"] == "claude"
        assert data["model"] == "claude-sonnet-4-5-20250514"
        assert data["usage"]["input_tokens"] == 10
        assert data["usage"]["output_tokens"] == 5
        assert data["usage"]["total_tokens"] == 15
        assert "session_id" in data

    def test_complete_gemini_success(self, client, mock_gemini_adapter):
        """Test successful Gemini completion."""
        response = client.post(
            "/api/complete",
            json={
                "model": "gemini-2.0-flash",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hi from Gemini!"
        assert data["provider"] == "gemini"

    def test_complete_with_session_id(self, client, mock_claude_adapter):
        """Test completion with existing session ID."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "session_id": "existing-session-123",
            },
        )

        assert response.status_code == 200
        assert response.json()["session_id"] == "existing-session-123"

    def test_complete_with_system_message(self, client, mock_claude_adapter):
        """Test completion with system message."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )

        assert response.status_code == 200
        # Verify adapter was called
        mock_claude_adapter.return_value.complete.assert_called_once()

    def test_complete_custom_params(self, client, mock_claude_adapter):
        """Test completion with custom parameters."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1000,
                "temperature": 0.5,
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1000
        assert call_kwargs["temperature"] == 0.5

    def test_complete_rate_limit_error(self, client):
        """Test rate limit error handling."""
        with patch("app.api.complete.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(side_effect=RateLimitError("claude", retry_after=30))
            mock.return_value = adapter

            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

            assert response.status_code == 429
            assert "Retry-After" in response.headers

    def test_complete_auth_error(self, client):
        """Test authentication error handling."""
        with patch("app.api.complete.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(side_effect=AuthenticationError("claude"))
            mock.return_value = adapter

            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

            assert response.status_code == 401

    def test_complete_provider_error(self, client):
        """Test generic provider error handling."""
        with patch("app.api.complete.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                side_effect=ProviderError("API error", provider="claude", status_code=503)
            )
            mock.return_value = adapter

            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

            assert response.status_code == 503

    def test_complete_missing_model(self, client):
        """Test validation error for missing model."""
        response = client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

        assert response.status_code == 422

    def test_complete_missing_messages(self, client):
        """Test validation error for missing messages."""
        response = client.post(
            "/api/complete",
            json={"model": "claude-sonnet-4-5-20250514"},
        )

        assert response.status_code == 422

    def test_complete_invalid_temperature(self, client):
        """Test validation error for invalid temperature."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 3.0,  # > 2.0 limit
            },
        )

        assert response.status_code == 422

    def test_complete_persist_session_false(self, client, mock_claude_adapter):
        """Test completion with persist_session=false doesn't save to db."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "persist_session": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data


class TestSessionPersistence:
    """Tests for session persistence in /complete endpoint."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock async database session."""
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_claude_adapter_for_persistence(self):
        """Mock ClaudeAdapter for persistence tests."""
        with patch("app.api.complete.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="I remember what you said!",
                    model="claude-sonnet-4-5-20250514",
                    provider="claude",
                    input_tokens=20,
                    output_tokens=10,
                    finish_reason="end_turn",
                )
            )
            mock.return_value = adapter
            yield mock

    def test_session_creates_on_first_request(
        self, mock_db_session, mock_claude_adapter_for_persistence
    ):
        """Test that a new session is created when no session_id provided."""
        from app.db import get_db

        # Mock no existing session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        client = TestClient(app)
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "persist_session": True,
            },
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        # Should have created a session and saved messages
        assert mock_db_session.add.called
        assert mock_db_session.commit.call_count >= 1

    def test_session_loads_context_on_resume(
        self, mock_db_session, mock_claude_adapter_for_persistence
    ):
        """Test that existing session messages are loaded as context."""
        from datetime import datetime

        from app.db import get_db

        # Mock existing session with messages
        mock_existing_session = MagicMock()
        mock_existing_session.id = "existing-session-123"
        mock_existing_session.project_id = "test-project"
        mock_existing_session.provider = "claude"
        mock_existing_session.model = "claude-sonnet-4-5"
        mock_existing_session.status = "active"

        # Mock existing messages
        mock_msg1 = MagicMock()
        mock_msg1.role = "user"
        mock_msg1.content = "Previous question"
        mock_msg1.created_at = datetime(2026, 1, 6, 10, 0, 0)

        mock_msg2 = MagicMock()
        mock_msg2.role = "assistant"
        mock_msg2.content = "Previous answer"
        mock_msg2.created_at = datetime(2026, 1, 6, 10, 1, 0)

        mock_existing_session.messages = [mock_msg1, mock_msg2]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_existing_session
        mock_db_session.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        client = TestClient(app)
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Follow-up question"}],
                "session_id": "existing-session-123",
                "persist_session": True,
            },
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "existing-session-123"

        # Check that the adapter was called with context messages + new message
        adapter = mock_claude_adapter_for_persistence.return_value
        call_args = adapter.complete.call_args
        messages = call_args.kwargs.get("messages", call_args.args[0] if call_args.args else [])
        # Should have: prev_user, prev_assistant, new_user = 3 messages
        assert len(messages) == 3
