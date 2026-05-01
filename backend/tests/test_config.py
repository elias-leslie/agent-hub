"""Configuration loading tests."""

from __future__ import annotations

from app.config import Settings


class TestSettings:
    def test_blank_dashboard_client_values_fall_back_to_built_in_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_HUB_DB_URL", "postgresql://agent_hub:password@localhost:5432/agent_hub")
        monkeypatch.setenv("AGENT_HUB_DASHBOARD_CLIENT_ID", "")
        monkeypatch.setenv("AGENT_HUB_DASHBOARD_REQUEST_SOURCE", "")

        settings = Settings(_env_file=None)

        assert settings.agent_hub_dashboard_client_id == "agent-hub-dashboard"
        assert settings.agent_hub_dashboard_request_source == "agent-hub-dashboard"

    def test_db_pool_defaults_are_conservative(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_HUB_DB_URL", "postgresql://agent_hub:password@localhost:5432/agent_hub")

        settings = Settings(_env_file=None)

        assert settings.agent_hub_db_pool_size == 3
        assert settings.agent_hub_db_max_overflow == 3
