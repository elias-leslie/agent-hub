"""Integration tests for /status endpoint."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestStatusEndpointIntegration:
    """Integration tests for status endpoint provider shape."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_response_format_matches_frontend_expectations(self):
        providers = [
            SimpleNamespace(api="anthropic-messages"),
            SimpleNamespace(api="openai-completions"),
        ]
        with patch("app.llm.api_registry.get_api_providers", return_value=providers):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/status")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "database" in data
        assert "providers" in data
        assert "uptime_seconds" in data
        assert data["circuit_breakers"] == {}
        assert data["thrashing_events_total"] == 0
        assert data["circuit_breaker_trips_total"] == 0

        for provider in data["providers"]:
            assert "name" in provider
            assert "available" in provider
            assert "configured" in provider
            assert provider["available"] is True
            assert provider["configured"] is True
