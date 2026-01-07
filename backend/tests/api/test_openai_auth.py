"""Tests for OpenAI-style API key authentication."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import CompletionResult
from app.main import app
from app.models import APIKey
from app.services.api_key_auth import (
    generate_api_key,
    hash_api_key,
    get_key_prefix,
    check_rate_limit,
    _rate_limits,
    KEY_PREFIX,
)


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


class TestAPIKeyGeneration:
    """Tests for API key generation functions."""

    def test_generate_api_key_format(self):
        """Generated keys have correct format."""
        full_key, key_hash = generate_api_key()

        assert full_key.startswith(KEY_PREFIX)
        assert len(full_key) > 20  # Reasonable minimum length
        assert len(key_hash) == 64  # SHA-256 hex

    def test_generate_unique_keys(self):
        """Each generated key is unique."""
        keys = [generate_api_key()[0] for _ in range(100)]
        assert len(set(keys)) == 100

    def test_hash_api_key(self):
        """Hashing is deterministic."""
        full_key, expected_hash = generate_api_key()
        actual_hash = hash_api_key(full_key)
        assert actual_hash == expected_hash

    def test_get_key_prefix(self):
        """Key prefix extraction."""
        full_key, _ = generate_api_key()
        prefix = get_key_prefix(full_key)

        assert prefix.startswith(KEY_PREFIX)
        assert len(prefix) == 14  # "sk-ah-" + 8 chars


class TestRateLimiting:
    """Tests for rate limiting logic."""

    def setup_method(self):
        """Clear rate limits before each test."""
        _rate_limits.clear()

    def test_rate_limit_allows_under_limit(self):
        """Requests under limit are allowed."""
        allowed, error = check_rate_limit("test_key", rpm_limit=10, tpm_limit=10000)
        assert allowed is True
        assert error is None

    def test_rate_limit_blocks_over_rpm(self):
        """Requests over RPM limit are blocked."""
        key = "rpm_test_key"

        # Make 10 requests (at limit)
        for _ in range(10):
            allowed, _ = check_rate_limit(key, rpm_limit=10, tpm_limit=100000)
            assert allowed is True

        # 11th request should be blocked
        allowed, error = check_rate_limit(key, rpm_limit=10, tpm_limit=100000)
        assert allowed is False
        assert "requests/minute" in error

    def test_rate_limit_blocks_over_tpm(self):
        """Requests over TPM limit are blocked."""
        key = "tpm_test_key"

        # Make request with high token count
        allowed, _ = check_rate_limit(
            key, rpm_limit=100, tpm_limit=1000, token_count=500
        )
        assert allowed is True

        # Another high-token request should exceed limit
        allowed, error = check_rate_limit(
            key, rpm_limit=100, tpm_limit=1000, token_count=600
        )
        assert allowed is False
        assert "tokens/minute" in error


class TestAPIKeyEndpoints:
    """Tests for API key management endpoints with mocked database."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        with patch("app.api.api_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()

            # Setup mock for scalars
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result

            # Make get_db return our mock
            async def mock_gen():
                yield mock_session
            mock_get_db.return_value = mock_gen()

            yield mock_session

    def test_create_api_key_format(self, client, mock_db):
        """Test API key creation returns correct format."""
        # Mock the add and commit
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Mock refresh to set attributes on the object
        async def mock_refresh(obj):
            obj.id = 1
            obj.created_at = datetime.utcnow()
        mock_db.refresh = mock_refresh

        response = client.post(
            "/api/api-keys",
            json={
                "name": "Test Key",
                "project_id": "test-project",
                "rate_limit_rpm": 100,
                "rate_limit_tpm": 50000,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Key"
        assert "key" in data
        assert data["key"].startswith(KEY_PREFIX)

    def test_get_api_key_not_found(self, client):
        """Get non-existent key returns 404."""
        response = client.get("/api/api-keys/99999")
        assert response.status_code == 404


class TestOpenAIEndpointAuth:
    """Tests for authentication in OpenAI-compatible endpoints."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        with patch("app.api.openai_compat.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hello!",
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
    def mock_valid_api_key(self):
        """Mock a valid API key in the database."""
        with patch("app.services.api_key_auth.validate_api_key") as mock_validate:
            mock_key = MagicMock(spec=APIKey)
            mock_key.id = 1
            mock_key.key_hash = "test_hash"
            mock_key.project_id = "test-project"
            mock_key.rate_limit_rpm = 60
            mock_key.rate_limit_tpm = 100000
            mock_key.is_active = 1
            mock_key.expires_at = None
            mock_validate.return_value = mock_key
            yield mock_validate

    @pytest.fixture
    def mock_update_last_used(self):
        """Mock update_key_last_used."""
        with patch("app.services.api_key_auth.update_key_last_used") as mock:
            mock.return_value = None
            yield mock

    def test_chat_completion_with_valid_key(
        self, client, mock_claude_adapter, mock_valid_api_key, mock_update_last_used
    ):
        """Chat completion works with valid API key."""
        _rate_limits.clear()  # Clear rate limits

        response = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": "Bearer sk-ah-valid-test-key"},
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        mock_valid_api_key.assert_called_once()

    def test_chat_completion_with_invalid_key(self, client, mock_claude_adapter):
        """Chat completion with invalid key returns 401."""
        with patch("app.services.api_key_auth.validate_api_key") as mock_validate:
            mock_validate.return_value = None  # Invalid key

            response = client.post(
                "/api/v1/chat/completions",
                headers={"Authorization": "Bearer sk-invalid-key"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 401
            data = response.json()
            assert "error" in data["detail"]
            assert data["detail"]["error"]["code"] == "invalid_api_key"

    def test_chat_completion_with_revoked_key(self, client, mock_claude_adapter):
        """Chat completion with revoked key returns 401."""
        with patch("app.services.api_key_auth.validate_api_key") as mock_validate:
            # validate_api_key returns None for revoked keys
            mock_validate.return_value = None

            response = client.post(
                "/api/v1/chat/completions",
                headers={"Authorization": "Bearer sk-ah-revoked-key"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 401

    def test_chat_completion_without_key_anonymous(self, client, mock_claude_adapter):
        """Chat completion without key works (anonymous access)."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        # Should still work - API keys are optional by default
        assert response.status_code == 200

    def test_models_endpoint_with_key(
        self, client, mock_valid_api_key, mock_update_last_used
    ):
        """Models endpoint works with API key."""
        _rate_limits.clear()

        response = client.get(
            "/api/v1/models",
            headers={"Authorization": "Bearer sk-ah-valid-test-key"},
        )

        assert response.status_code == 200

    def test_invalid_auth_header_format(self, client, mock_claude_adapter):
        """Invalid auth header format returns 401."""
        response = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": "Basic invalid"},
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 401
        assert "invalid_auth_header" in response.json()["detail"]["error"]["code"]

    def test_rate_limit_exceeded(
        self, client, mock_claude_adapter, mock_valid_api_key, mock_update_last_used
    ):
        """Rate limit exceeded returns 429."""
        _rate_limits.clear()

        # Set up rate limit to be exceeded
        with patch("app.services.api_key_auth.check_rate_limit") as mock_check:
            mock_check.return_value = (False, "Rate limit exceeded")

            response = client.post(
                "/api/v1/chat/completions",
                headers={"Authorization": "Bearer sk-ah-limited-key"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 429
