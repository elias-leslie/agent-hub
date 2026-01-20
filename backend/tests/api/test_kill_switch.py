"""Tests for kill switch API endpoints.

These tests use mocked database responses by default.
Run with --run-integration to test against a real database.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    mock = AsyncMock()
    return mock


@pytest.fixture
async def async_client():
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestClientControlEndpoints:
    """Tests for /api/admin/clients endpoints."""

    async def test_list_clients_empty(self, async_client):
        """Test listing clients when none exist."""
        response = await async_client.get("/api/admin/clients")
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert "total" in data

    async def test_disable_client(self, async_client):
        """Test disabling a client."""
        response = await async_client.post(
            "/api/admin/clients/test-client/disable",
            json={"reason": "Test disable", "disabled_by": "test-user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["client_name"] == "test-client"
        assert data["enabled"] is False
        assert data["reason"] == "Test disable"

    async def test_enable_client(self, async_client):
        """Test re-enabling a disabled client."""
        # First disable
        await async_client.post(
            "/api/admin/clients/test-client2/disable",
            json={"reason": "Test", "disabled_by": "test"},
        )
        # Then enable
        response = await async_client.delete("/api/admin/clients/test-client2/disable")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True


class TestPurposeControlEndpoints:
    """Tests for /api/admin/purposes endpoints."""

    async def test_list_purposes_empty(self, async_client):
        """Test listing purposes when none exist."""
        response = await async_client.get("/api/admin/purposes")
        assert response.status_code == 200
        data = response.json()
        assert "purposes" in data
        assert "total" in data

    async def test_disable_purpose(self, async_client):
        """Test disabling a purpose."""
        response = await async_client.post(
            "/api/admin/purposes/code_generation/disable",
            json={"reason": "Test disable", "disabled_by": "test-user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["purpose"] == "code_generation"
        assert data["enabled"] is False


class TestKillSwitchMiddleware:
    """Tests for the kill switch middleware."""

    async def test_exempt_paths_no_header_required(self, async_client):
        """Test that exempt paths don't require X-Source-Client header."""
        response = await async_client.get("/health")
        assert response.status_code == 200

    async def test_admin_paths_exempt(self, async_client):
        """Test that admin paths are exempt from kill switch."""
        response = await async_client.get("/api/admin/clients")
        assert response.status_code == 200

    @pytest.mark.integration
    async def test_api_requires_source_header(self, async_client):
        """Test that API paths require X-Source-Client header."""
        response = await async_client.get("/api/sessions")
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "missing_source_header"

    @pytest.mark.integration
    async def test_api_accepts_source_header(self, async_client):
        """Test that API paths accept valid X-Source-Client header."""
        response = await async_client.get(
            "/api/sessions",
            headers={"X-Source-Client": "test-client"},
        )
        # May return 200 or other status, but not 400 for missing header
        assert response.status_code != 400


class TestBlockedRequestsLog:
    """Tests for blocked requests logging."""

    async def test_get_blocked_requests(self, async_client):
        """Test getting blocked requests log."""
        response = await async_client.get("/api/admin/blocked-requests")
        assert response.status_code == 200
        data = response.json()
        assert "requests" in data
        assert "total" in data

    async def test_blocked_requests_limit(self, async_client):
        """Test blocked requests limit parameter."""
        response = await async_client.get("/api/admin/blocked-requests?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) <= 10
