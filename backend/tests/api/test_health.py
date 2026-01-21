"""Tests for health, status, and metrics endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import TEST_HEADERS


@pytest.fixture
async def client():
    """Async test client with source headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,  # Add test headers for kill switch compliance
    ) as ac:
        yield ac


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        """Basic liveness check returns 200 OK."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-hub"

    @pytest.mark.asyncio
    async def test_api_health_returns_200(self, client: AsyncClient):
        """API health endpoint returns 200 OK."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-hub"


class TestStatusEndpoint:
    """Tests for /api/status endpoint."""

    @pytest.mark.asyncio
    async def test_status_returns_diagnostics(self, client: AsyncClient):
        """Status endpoint returns detailed diagnostics."""
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()

        # Check structure
        assert "status" in data
        assert "service" in data
        assert "database" in data
        assert "providers" in data
        assert "uptime_seconds" in data

        # Service name
        assert data["service"] == "agent-hub"

        # Database status should be a string
        assert isinstance(data["database"], str)

        # Providers should be a list
        assert isinstance(data["providers"], list)
        assert len(data["providers"]) >= 1  # At least claude

        # Each provider has required fields
        for provider in data["providers"]:
            assert "name" in provider
            assert "available" in provider
            assert "configured" in provider

        # Uptime should be positive
        assert data["uptime_seconds"] > 0

    @pytest.mark.asyncio
    async def test_status_includes_claude_provider(self, client: AsyncClient):
        """Status includes Claude provider info."""
        response = await client.get("/api/status")
        data = response.json()

        claude_providers = [p for p in data["providers"] if p["name"] == "claude"]
        assert len(claude_providers) == 1

    @pytest.mark.asyncio
    async def test_status_includes_gemini_provider(self, client: AsyncClient):
        """Status includes Gemini provider info."""
        response = await client.get("/api/status")
        data = response.json()

        gemini_providers = [p for p in data["providers"] if p["name"] == "gemini"]
        assert len(gemini_providers) == 1


class TestMetricsEndpoint:
    """Tests for /api/metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_format(self, client: AsyncClient):
        """Metrics endpoint returns Prometheus text format."""
        response = await client.get("/api/metrics")
        assert response.status_code == 200

        # Check content type
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type

        # Check content structure
        content = response.text
        assert "# HELP" in content
        assert "# TYPE" in content
        assert "agent_hub_requests_total" in content
        assert "agent_hub_errors_total" in content
        assert "agent_hub_active_sessions" in content
        assert "agent_hub_uptime_seconds" in content

    @pytest.mark.asyncio
    async def test_metrics_includes_latency(self, client: AsyncClient):
        """Metrics includes request latency histogram."""
        response = await client.get("/api/metrics")
        content = response.text

        assert "agent_hub_request_latency_ms_sum" in content
        assert "agent_hub_request_latency_ms_count" in content

    @pytest.mark.asyncio
    async def test_metrics_counters_are_numbers(self, client: AsyncClient):
        """Metrics counters contain numeric values."""
        response = await client.get("/api/metrics")
        content = response.text

        # Find the requests_total line
        for line in content.split("\n"):
            if line.startswith("agent_hub_requests_total"):
                # Should be "agent_hub_requests_total <number>"
                parts = line.split()
                assert len(parts) == 2
                # Value should be parseable as int
                int(parts[1])
                break
