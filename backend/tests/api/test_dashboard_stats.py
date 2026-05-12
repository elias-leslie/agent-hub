from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


class TestDashboardProviderHealthEndpoint:
    def test_provider_health_reports_registered_providers(self, api_client) -> None:
        providers = [
            SimpleNamespace(api="anthropic-messages"),
            SimpleNamespace(api="google-generative-ai"),
        ]

        with patch("app.llm.api_registry.get_api_providers", return_value=providers):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "provider": "anthropic-messages",
                    "state": "healthy",
                    "latency_ms": 0.0,
                    "availability": 100.0,
                    "consecutive_failures": 0,
                    "last_error": None,
                },
                {
                    "provider": "google-generative-ai",
                    "state": "healthy",
                    "latency_ms": 0.0,
                    "availability": 100.0,
                    "consecutive_failures": 0,
                    "last_error": None,
                },
            ]
        }
