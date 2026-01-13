"""Integration tests for /status endpoint with health prober."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestStatusEndpointIntegration:
    """Integration tests for status endpoint with provider health."""

    @pytest.fixture
    def mock_health_prober(self):
        """Create mock health prober with test data."""
        from app.services.health_prober import ProviderHealth, ProviderState

        prober = MagicMock()
        prober.get_all_health.return_value = {
            "claude": ProviderHealth(
                name="claude",
                state=ProviderState.HEALTHY,
                last_check=1704582000.0,
                last_success=1704582000.0,
                latency_ms=150.0,
                success_count=10,
                error_count=0,
            ),
            "gemini": ProviderHealth(
                name="gemini",
                state=ProviderState.DEGRADED,
                last_check=1704582000.0,
                last_success=1704581900.0,
                latency_ms=5500.0,
                success_count=8,
                error_count=2,
                consecutive_failures=2,
                last_error="High latency",
            ),
        }
        return prober

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_returns_provider_health_details(self, mock_health_prober):
        """Test that /status includes provider health details from prober."""
        with (
            patch("app.services.health_prober.get_health_prober", return_value=mock_health_prober),
            patch("app.api.health.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.gemini_api_key = "test-key"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/status")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] in ("healthy", "degraded")
            assert "providers" in data
            assert len(data["providers"]) >= 1

            # Check provider has health details
            for provider in data["providers"]:
                if provider["health"]:
                    assert "state" in provider["health"]
                    assert "latency_ms" in provider["health"]
                    assert "availability" in provider["health"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_shows_degraded_provider(self, mock_health_prober):
        """Test that degraded provider is reported in status."""
        with (
            patch("app.services.health_prober.get_health_prober", return_value=mock_health_prober),
            patch("app.api.health.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.gemini_api_key = "test-key"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/status")

            data = response.json()
            gemini = next((p for p in data["providers"] if p["name"] == "gemini"), None)

            if gemini and gemini["health"]:
                assert gemini["health"]["state"] == "degraded"
                assert gemini["health"]["last_error"] == "High latency"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_response_format_matches_frontend_expectations(self, mock_health_prober):
        """Test that status response format matches what frontend expects."""
        with (
            patch("app.services.health_prober.get_health_prober", return_value=mock_health_prober),
            patch("app.api.health.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.gemini_api_key = "test-key"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/status")

            data = response.json()

            # Frontend expects these fields (from use-provider-status.ts)
            assert "status" in data
            assert "service" in data
            assert "database" in data
            assert "providers" in data
            assert "uptime_seconds" in data

            # Provider format expected by frontend
            for provider in data["providers"]:
                assert "name" in provider
                assert "available" in provider
                assert "configured" in provider
                # health may be null if prober hasn't run
                if provider["health"]:
                    assert "state" in provider["health"]
                    assert "latency_ms" in provider["health"]
                    assert "error_rate" in provider["health"]
                    assert "availability" in provider["health"]
