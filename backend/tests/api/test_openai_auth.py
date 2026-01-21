"""Tests for API key authentication."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import app
from app.services.api_key_auth import (
    KEY_PREFIX,
    _rate_limits,
    check_rate_limit,
    generate_api_key,
    get_key_prefix,
    hash_api_key,
)
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    return APITestClient(app)


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
        allowed, _ = check_rate_limit(key, rpm_limit=100, tpm_limit=1000, token_count=500)
        assert allowed is True

        # Another high-token request should exceed limit
        allowed, error = check_rate_limit(key, rpm_limit=100, tpm_limit=1000, token_count=600)
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
            obj.created_at = datetime.now(UTC)

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
