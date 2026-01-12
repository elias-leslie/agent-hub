"""Tests for /complete endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    ProviderError,
    RateLimitError,
)
from app.api.complete import clear_adapter_cache
from app.main import app


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_adapter_cache():
    """Clear adapter cache before each test."""
    clear_adapter_cache()
    yield
    clear_adapter_cache()


class TestCompleteEndpoint:
    """Tests for POST /api/complete."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        # Mock shutil.which to avoid OAuth mode
        with patch("app.adapters.claude.shutil.which", return_value=None):
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
                    model="gemini-3-flash-preview",
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
                "project_id": "test-project",
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
                "model": "gemini-3-flash-preview",
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
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
                "project_id": "test-project",
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
                "project_id": "test-project",
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
                "project_id": "test-project",
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
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(side_effect=RateLimitError("claude", retry_after=30))

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 429
            assert "Retry-After" in response.headers

    def test_complete_auth_error(self, client):
        """Test authentication error handling."""
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(side_effect=AuthenticationError("claude"))

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 401

    def test_complete_provider_error(self, client):
        """Test generic provider error handling."""
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            side_effect=ProviderError("API error", provider="claude", status_code=503)
        )

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 503

    def test_complete_missing_model(self, client):
        """Test validation error for missing model."""
        response = client.post(
            "/api/complete",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
            },
        )

        assert response.status_code == 422

    def test_complete_missing_messages(self, client):
        """Test validation error for missing messages."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "project_id": "test-project",
            },
        )

        assert response.status_code == 422

    def test_complete_missing_project_id(self, client):
        """Test validation error for missing project_id (required)."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        assert response.status_code == 422

    def test_complete_invalid_temperature(self, client):
        """Test validation error for invalid temperature."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
                "temperature": 3.0,  # > 2.0 limit
            },
        )

        assert response.status_code == 422

    def test_complete_with_purpose(self, client, mock_claude_adapter):
        """Test completion with purpose field."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "purpose": "task_enrichment",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
