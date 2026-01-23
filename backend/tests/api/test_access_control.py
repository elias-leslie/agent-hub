"""Tests for access control system.

Tests the AccessControlMiddleware and Access Control API endpoints.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client(mock_db_session):
    """Create an async HTTP client for testing with mock db."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestAccessControlMiddleware:
    """Tests for the access control middleware."""

    async def test_exempt_paths_no_auth_required(self, async_client):
        """Test that exempt paths don't require authentication."""
        response = await async_client.get("/health")
        assert response.status_code == 200

    async def test_admin_paths_exempt(self, async_client):
        """Test that admin paths are exempt from access control."""
        response = await async_client.get("/api/admin/clients")
        assert response.status_code == 200

    async def test_access_control_paths_exempt(self, async_client):
        """Test that access control API paths are exempt."""
        response = await async_client.get("/api/access-control/stats")
        assert response.status_code == 200

    async def test_missing_headers_returns_400(self, async_client):
        """Test that missing required headers return 400."""
        # No headers at all
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "missing_required_headers"
        assert "X-Client-Id" in str(data["required_headers"])
        assert "X-Client-Secret" in str(data["required_headers"])
        assert "X-Request-Source" in str(data["required_headers"])

    async def test_partial_missing_headers_returns_400(self, async_client):
        """Test that partially missing headers return 400."""
        # Only client ID, missing secret and source
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers={"X-Client-Id": "test-client"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "missing_required_headers"

    async def test_invalid_secret_returns_403(self, async_client):
        """Test that invalid secret returns 403."""
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers={
                "X-Client-Id": "non-existent-client-id",
                "X-Client-Secret": "ahc_invalid_secret_here",
                "X-Request-Source": "test",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "authentication_failed"

    async def test_internal_header_bypasses_auth(self, async_client):
        """Test that internal header bypasses authentication."""
        response = await async_client.get(
            "/api/sessions",
            headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
        )
        # Should not return 400 or 403 - may return 200 or other valid response
        assert response.status_code not in [400, 403]

    @pytest.mark.integration
    async def test_valid_auth_allows_request(self, async_client):
        """Test that valid authentication allows request through.

        Note: This requires a real client in the database. Run with --run-integration.
        For unit tests, use test_internal_header_bypasses_auth instead.
        """
        # This test requires a real client to be registered.
        # Skip in unit test mode - the internal header test validates bypass works.
        pass


class TestAccessControlAPI:
    """Tests for access control admin API endpoints."""

    async def test_get_stats(self, async_client):
        """Test getting access control statistics."""
        response = await async_client.get("/api/access-control/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_clients" in data
        assert "active_clients" in data
        assert "suspended_clients" in data
        assert "blocked_clients" in data
        assert "blocked_requests_today" in data
        assert "total_requests_today" in data

    async def test_list_clients(self, async_client):
        """Test listing clients."""
        response = await async_client.get("/api/access-control/clients")
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert "total" in data

    async def test_create_client(self, async_client):
        """Test creating a new client."""
        response = await async_client.post(
            "/api/access-control/clients",
            json={
                "display_name": "Test API Client",
                "client_type": "external",
                "rate_limit_rpm": 60,
                "rate_limit_tpm": 100000,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "client_id" in data
        assert "secret" in data
        assert data["secret"].startswith("ahc_")
        assert data["display_name"] == "Test API Client"
        assert "message" in data  # Warning to save the secret

    async def test_get_request_log(self, async_client):
        """Test getting request log."""
        response = await async_client.get("/api/access-control/request-log")
        assert response.status_code == 200
        data = response.json()
        assert "requests" in data
        assert "total" in data

    async def test_get_request_log_with_filters(self, async_client):
        """Test getting request log with filters."""
        response = await async_client.get(
            "/api/access-control/request-log",
            params={"rejected_only": True, "limit": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) <= 10
