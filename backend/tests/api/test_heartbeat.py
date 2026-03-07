"""Tests for heartbeat API endpoints (app/api/heartbeat.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestHeartbeatStatus:
    """Tests for GET /api/heartbeat/status."""

    def test_heartbeat_status_when_idle_returns_not_running(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T10:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = api_client.get("/api/heartbeat/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["last_run"] == "2026-03-03T10:00:00+00:00"
        assert data["elapsed_seconds"] is None
        assert data["interval_minutes"] == 60

    def test_heartbeat_status_when_running_returns_running(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value={"started_at": "2026-03-03T10:00:00+00:00", "elapsed_seconds": 45},
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T09:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = api_client.get("/api/heartbeat/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["elapsed_seconds"] == 45

    def test_heartbeat_status_when_never_run_returns_null_last_run(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = api_client.get("/api/heartbeat/status")

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["last_run"] is None

    def test_heartbeat_status_includes_runtime_metadata(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T10:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value={
                    "model": "codex/gpt-5.4",
                    "provider": "codex",
                    "model_display_name": "GPT-5.4 (Codex)",
                    "thinking_level": "medium",
                    "supports_tools": True,
                    "supports_thinking": True,
                    "supports_verbosity": True,
                    "supports_session_cache": True,
                    "heartbeat_supported": True,
                    "warnings": [],
                },
            ),
        ):
            response = api_client.get("/api/heartbeat/status")

        assert response.status_code == 200
        data = response.json()
        assert data["runtime"]["model"] == "codex/gpt-5.4"
        assert data["runtime"]["provider"] == "codex"
        assert data["runtime"]["heartbeat_supported"] is True
        assert data["runtime"]["supports_tools"] is True


class TestHeartbeatTrigger:
    """Tests for POST /api/heartbeat/trigger."""

    def test_heartbeat_trigger_when_idle_dispatches_task(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.persona_heartbeat_task",
            ) as mock_task,
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dispatched"
        mock_task.run_no_wait.assert_called_once()

    def test_heartbeat_trigger_when_running_returns_409(self, api_client):
        with patch(
            "app.api.heartbeat.get_heartbeat_running_info",
            new_callable=AsyncMock,
            return_value={"started_at": "2026-03-03T10:00:00+00:00", "elapsed_seconds": 30},
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 409
        assert "already in progress" in response.json()["message"]

    def test_heartbeat_trigger_when_not_onboarded_returns_400(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, False),
            ),
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 400
        assert "onboarding" in response.json()["message"]

    def test_heartbeat_trigger_when_permission_denied_returns_403(self, api_client):
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 403
        assert "permission" in response.json()["message"]
