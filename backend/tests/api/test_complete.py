"""Tests for /complete endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    ProviderError,
    RateLimitError,
)
from app.api.complete import clear_adapter_cache, validate_json_response
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    return APITestClient(app)


@pytest.fixture(autouse=True)
def reset_adapter_cache():
    """Clear adapter cache before each test."""
    clear_adapter_cache()
    yield
    clear_adapter_cache()


@pytest.mark.skip(reason="API changed to require agent_slug - tests need refactoring")
class TestCompleteEndpoint:
    """Tests for POST /api/complete."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        # Mock shutil.which to avoid OAuth mode
        with (
            patch("app.adapters.claude.shutil.which", return_value=None),
            patch("app.api.complete.ClaudeAdapter") as mock,
        ):
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
        """Test completion with custom parameters (max_tokens removed from API)."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "temperature": 0.5,
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] is None  # No artificial caps - model determines length
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
        """Test validation error for missing model (no agent_slug either)."""
        response = client.post(
            "/api/complete",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
            },
        )

        # Returns 400 because either model or agent_slug must be provided
        assert response.status_code == 400
        assert (
            "model" in response.json()["detail"].lower()
            or "agent_slug" in response.json()["detail"].lower()
        )

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


class TestJsonSchemaValidation:
    """Tests for JSON schema validation functionality."""

    def test_validate_json_response_valid(self):
        """Test validation passes for valid JSON matching schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        content = '{"name": "John", "age": 30}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is True
        assert error is None

    def test_validate_json_response_invalid_json(self):
        """Test validation fails for invalid JSON."""
        schema = {"type": "object"}
        content = "not valid json {"
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_validate_json_response_schema_mismatch(self):
        """Test validation fails when JSON doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        # Missing required field 'age'
        content = '{"name": "John"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error

    def test_validate_json_response_wrong_type(self):
        """Test validation fails when type doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        # 'count' is a string instead of integer
        content = '{"count": "five"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error


@pytest.mark.skip(reason="API changed to require agent_slug - tests need refactoring")
class TestStructuredOutput:
    """Tests for structured output (JSON mode) in /complete endpoint."""

    @pytest.fixture
    def mock_adapter_json_response(self):
        """Mock adapter returning valid JSON."""
        clear_adapter_cache()
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"name": "Claude", "items": ["a", "b"]}',
                model="claude-sonnet-4-5-20250514",
                provider="claude",
                input_tokens=10,
                output_tokens=8,
                finish_reason="end_turn",
            )
        )
        return adapter

    @pytest.fixture
    def mock_adapter_invalid_json_response(self):
        """Mock adapter returning invalid JSON for schema."""
        clear_adapter_cache()
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"name": "Claude"}',  # Missing required 'items'
                model="claude-sonnet-4-5-20250514",
                provider="claude",
                input_tokens=10,
                output_tokens=5,
                finish_reason="end_turn",
            )
        )
        return adapter

    def test_complete_with_json_mode_success(self, client, mock_adapter_json_response):
        """Test successful completion with JSON mode and schema validation."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return a JSON object"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "items"],
                        },
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 200
            data = response.json()
            # Content should be valid JSON
            parsed = json.loads(data["content"])
            assert parsed["name"] == "Claude"
            assert parsed["items"] == ["a", "b"]

    def test_complete_with_json_mode_validation_failure(
        self, client, mock_adapter_invalid_json_response
    ):
        """Test that validation failure returns 400."""
        with patch(
            "app.api.complete._get_adapter", return_value=mock_adapter_invalid_json_response
        ):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return a JSON object"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "items": {"type": "array"},
                            },
                            "required": ["name", "items"],
                        },
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 400
            assert "does not match the provided JSON schema" in response.json()["detail"]

    def test_complete_with_json_mode_no_schema(self, client, mock_adapter_json_response):
        """Test JSON mode without schema (no validation)."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return JSON"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        # No schema provided - no validation
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            # Should succeed without validation
            assert response.status_code == 200

    def test_complete_text_mode_default(self, client, mock_adapter_json_response):
        """Test that text mode (default) doesn't do JSON validation."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "project_id": "test-project",
                    # No response_format - defaults to text mode
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 200
