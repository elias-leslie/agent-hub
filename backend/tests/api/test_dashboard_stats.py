from __future__ import annotations

from unittest.mock import patch


class TestDashboardProviderHealthEndpoint:
    def test_provider_health_reports_routing_provider_readiness(self, api_client) -> None:
        async def reason(provider: str) -> str | None:
            return None if provider == "codex" else "no credential is stored for provider gemini"

        with (
            patch("app.routing.registry.list_workload_providers", return_value=["codex", "gemini"]),
            patch("app.routing.availability.provider_unavailable_reason", side_effect=reason),
        ):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "provider": "codex",
                    "state": "ready",
                    "latency_ms": None,
                    "availability": None,
                    "consecutive_failures": 0,
                    "last_error": None,
                },
                {
                    "provider": "gemini",
                    "state": "unavailable",
                    "latency_ms": None,
                    "availability": None,
                    "consecutive_failures": 0,
                    "last_error": "no credential is stored for provider gemini",
                },
            ]
        }
