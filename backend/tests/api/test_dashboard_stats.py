from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.health_prober import ProviderHealth, ProviderState


class TestDashboardProviderHealthEndpoint:
    def test_provider_health_filters_unconfigured_providers_and_probes_live(
        self, api_client
    ) -> None:
        claude = ProviderHealth(name="claude")
        openai = ProviderHealth(name="openai")
        prober = MagicMock()
        prober._adapters = {"claude": object()}
        prober.get_all_health.return_value = {
            "claude": claude,
            "openai": openai,
        }

        async def probe_now(provider: str) -> None:
            assert provider == "claude"
            claude.state = ProviderState.HEALTHY
            claude.last_check = 1704582000.0
            claude.last_success = 1704582000.0
            claude.latency_ms = 123.4
            claude.success_count = 1
            claude.error_count = 0
            claude.consecutive_failures = 0
            claude.last_error = None

        prober.probe_now = AsyncMock(side_effect=probe_now)

        with patch("app.services.health_prober.get_health_prober", return_value=prober):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "provider": "claude",
                    "state": "healthy",
                    "latency_ms": 123.4,
                    "availability": 100.0,
                    "consecutive_failures": 0,
                    "last_error": None,
                }
            ]
        }
        prober.probe_now.assert_awaited_once_with("claude")

    def test_provider_health_refreshes_stale_down_state(self, api_client) -> None:
        gemini = ProviderHealth(
            name="gemini",
            state=ProviderState.DOWN,
            last_check=1704581000.0,
            last_success=1704580000.0,
            latency_ms=8000.0,
            success_count=4,
            error_count=3,
            consecutive_failures=3,
            last_error="stale outage",
        )
        prober = MagicMock()
        prober._adapters = {"gemini": object()}
        prober.get_all_health.return_value = {"gemini": gemini}

        async def probe_now(provider: str) -> None:
            assert provider == "gemini"
            gemini.state = ProviderState.HEALTHY
            gemini.last_check = 1704583000.0
            gemini.last_success = 1704583000.0
            gemini.latency_ms = 210.0
            gemini.success_count = 5
            gemini.consecutive_failures = 0
            gemini.last_error = None

        prober.probe_now = AsyncMock(side_effect=probe_now)

        with patch("app.services.health_prober.get_health_prober", return_value=prober):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json()["providers"][0]["state"] == "healthy"
        assert response.json()["providers"][0]["last_error"] is None

    def test_provider_health_maps_failed_probe_to_down(self, api_client) -> None:
        codex = ProviderHealth(name="codex")
        prober = MagicMock()
        prober._adapters = {"codex": object()}
        prober.get_all_health.return_value = {"codex": codex}

        async def probe_now(provider: str) -> None:
            assert provider == "codex"
            codex.state = ProviderState.UNKNOWN
            codex.last_check = 1704584000.0
            codex.latency_ms = 25.0
            codex.success_count = 0
            codex.error_count = 1
            codex.consecutive_failures = 1
            codex.last_error = "token expired"

        prober.probe_now = AsyncMock(side_effect=probe_now)

        with patch("app.services.health_prober.get_health_prober", return_value=prober):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "provider": "codex",
                    "state": "down",
                    "latency_ms": 25.0,
                    "availability": 0.0,
                    "consecutive_failures": 1,
                    "last_error": "token expired",
                }
            ]
        }
