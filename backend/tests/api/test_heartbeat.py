"""Tests for heartbeat API endpoints (app/api/heartbeat.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestHeartbeatStatus:
    """Tests for GET /api/heartbeat/status."""

    def test_heartbeat_status_when_idle_returns_not_running(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T10:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_state",
                new_callable=AsyncMock,
                return_value={
                    "last_attempt": "2026-03-03T10:00:00+00:00",
                    "last_success": "2026-03-03T10:00:00+00:00",
                    "last_skip_reason": "",
                    "last_error": "",
                    "last_session_id": "sess-1",
                },
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_metrics",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
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
        assert data["last_attempt"] == "2026-03-03T10:00:00+00:00"
        assert data["last_success"] == "2026-03-03T10:00:00+00:00"
        assert data["elapsed_seconds"] is None
        assert data["interval_minutes"] == 60
        assert data["execution_state"] == "active"
        assert data["last_session_id"] == "sess-1"

    def test_heartbeat_status_when_running_returns_running(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value={
                    "started_at": "2026-03-03T10:00:00+00:00",
                    "elapsed_seconds": 45,
                    "session_id": "hb-session-1",
                    "owner_host": "summitflow-prod",
                    "owner_pid": 4242,
                    "trigger": "manual_api",
                    "project_id": "agent-hub",
                },
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T09:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_state",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_metrics",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
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
        assert data["running_session_id"] == "hb-session-1"
        assert data["running_owner_host"] == "summitflow-prod"
        assert data["running_owner_pid"] == 4242
        assert data["running_trigger"] == "manual_api"
        assert data["running_project_id"] == "agent-hub"

    def test_heartbeat_status_when_never_run_returns_null_last_run(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_state",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_metrics",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
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
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-03-03T10:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_state",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_metrics",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
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

    @pytest.mark.asyncio
    async def test_get_effective_running_info_clears_stale_lock(self) -> None:
        with (
            patch(
                "app.api.heartbeat.get_heartbeat_running_info",
                new_callable=AsyncMock,
                return_value={
                    "started_at": "2026-03-03T10:00:00+00:00",
                    "elapsed_seconds": 400,
                    "session_id": "hb-session-1",
                },
            ),
            patch(
                "app.api.heartbeat._has_live_heartbeat_session",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            from app.api.heartbeat import _get_effective_running_info

            result = await _get_effective_running_info()

        assert result is None
        mock_clear.assert_awaited_once_with(
            claim_token=None,
            session_id="hb-session-1",
        )

    def test_heartbeat_status_reports_current_skip_without_rewriting_last_success(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_last_run_info",
                new_callable=AsyncMock,
                return_value="2026-04-01T10:00:00+00:00",
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_state",
                new_callable=AsyncMock,
                return_value={
                    "last_attempt": "2026-04-20T13:40:00+00:00",
                    "last_success": "2026-04-01T10:00:00+00:00",
                    "last_skip_reason": "schedule_disabled",
                    "last_error": "",
                    "last_session_id": "old-success-session",
                },
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_metrics",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
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
        assert data["running_session_id"] is None
        assert data["last_attempt"] == "2026-04-20T13:40:00+00:00"
        assert data["last_skip_reason"] == "schedule_disabled"
        assert data["last_run"] == "2026-04-01T10:00:00+00:00"
        assert data["last_success"] == "2026-04-01T10:00:00+00:00"
        assert data["last_session_id"] == "old-success-session"


class TestHeartbeatTrigger:
    """Tests for POST /api/heartbeat/trigger."""


    def test_heartbeat_trigger_when_schedule_disabled_returns_skipped_without_dispatch(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_running,
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.heartbeat.record_heartbeat_skip",
                new_callable=AsyncMock,
            ) as mock_skip,
            patch(
                "app.api.heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.api.heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
            patch("app.api.heartbeat.persona_heartbeat_task") as mock_task,
        ):
            mock_task.aio_run_no_wait = AsyncMock()
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data == {
            "status": "skipped",
            "message": "Heartbeat skipped (schedule disabled)",
            "session_id": None,
        }
        mock_running.assert_awaited_once()
        mock_skip.assert_awaited_once_with("schedule_disabled")
        mock_attempt.assert_not_awaited()
        mock_set_running.assert_not_awaited()
        mock_task.aio_run_no_wait.assert_not_called()

    def test_heartbeat_trigger_when_idle_dispatches_task(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.api.heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value="claim-api-123",
            ) as mock_set_running,
            patch(
                "app.api.heartbeat.persona_heartbeat_task",
            ) as mock_task,
            patch(
                "app.api.heartbeat.create_heartbeat_session_id",
                return_value="hb-session-123",
            ),
        ):
            mock_task.aio_run_no_wait = AsyncMock()
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dispatched"
        assert data["session_id"] == "hb-session-123"
        mock_attempt.assert_awaited_once_with(session_id="hb-session-123")
        mock_set_running.assert_awaited_once_with(
            session_id="hb-session-123",
            trigger="manual_api",
            project_id="persona-sandbox",
            only_if_missing=True,
        )
        mock_task.aio_run_no_wait.assert_awaited_once()
        heartbeat_input = mock_task.aio_run_no_wait.call_args.kwargs["input"]
        assert heartbeat_input.heartbeat_session_id == "hb-session-123"
        assert heartbeat_input.running_claimed is True
        assert heartbeat_input.running_claim_token == "claim-api-123"

    def test_heartbeat_trigger_with_target_project_dispatches_scoped_run(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_permission,
            patch(
                "app.api.heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.api.heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value="claim-api-agent-hub",
            ) as mock_set_running,
            patch(
                "app.api.heartbeat.persona_heartbeat_task",
            ) as mock_task,
            patch(
                "app.constants.VALID_PROJECT_IDS",
                frozenset({"agent-hub", "persona-sandbox"}),
            ),
            patch(
                "app.api.heartbeat.create_heartbeat_session_id",
                return_value="hb-session-agent-hub",
            ),
        ):
            mock_task.aio_run_no_wait = AsyncMock()
            response = api_client.post("/api/heartbeat/trigger", json={"target_project_id": "agent-hub"})

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Heartbeat triggered for agent-hub"
        assert data["session_id"] == "hb-session-agent-hub"
        mock_attempt.assert_awaited_once_with(session_id="hb-session-agent-hub")
        mock_set_running.assert_awaited_once_with(
            session_id="hb-session-agent-hub",
            trigger="manual_api",
            project_id="agent-hub",
            only_if_missing=True,
        )
        mock_permission.assert_awaited_once_with("agent-hub")
        mock_task.aio_run_no_wait.assert_awaited_once()
        heartbeat_input = mock_task.aio_run_no_wait.call_args.kwargs["input"]
        assert heartbeat_input.manual is True
        assert heartbeat_input.target_project_id == "agent-hub"
        assert heartbeat_input.heartbeat_session_id == "hb-session-agent-hub"
        assert heartbeat_input.running_claimed is True
        assert heartbeat_input.running_claim_token == "claim-api-agent-hub"

    def test_heartbeat_trigger_when_running_returns_409(self, api_client):
        with patch(
            "app.api.heartbeat._get_effective_running_info",
            new_callable=AsyncMock,
            return_value={
                "started_at": "2026-03-03T10:00:00+00:00",
                "elapsed_seconds": 30,
                "session_id": "hb-session-running",
            },
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 409
        assert "already in progress" in response.json()["message"]
        assert response.json()["running_session_id"] == "hb-session-running"

    def test_heartbeat_trigger_clears_reserved_lock_if_dispatch_fails(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value="claim-api-fail",
            ),
            patch(
                "app.api.heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_clear,
            patch(
                "app.api.heartbeat.persona_heartbeat_task",
            ) as mock_task,
            patch(
                "app.api.heartbeat.create_heartbeat_session_id",
                return_value="hb-session-fail",
            ),
        ):
            mock_task.aio_run_no_wait = AsyncMock(side_effect=RuntimeError("queue unavailable"))
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 503
        assert "Failed to dispatch heartbeat" in response.json()["message"]
        mock_clear.assert_awaited_once_with(
            claim_token="claim-api-fail",
            session_id="hb-session-fail",
        )

    def test_heartbeat_trigger_returns_409_when_atomic_claim_fails(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                side_effect=[
                    None,
                    {
                        "started_at": "2026-03-03T10:00:00+00:00",
                        "elapsed_seconds": 3,
                        "session_id": "hb-session-live",
                        "owner_host": "summitflow-prod",
                        "owner_pid": 5150,
                        "trigger": "cron",
                        "project_id": "persona-sandbox",
                    },
                ],
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.api.heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_set_running,
            patch(
                "app.api.heartbeat.persona_heartbeat_task",
            ) as mock_task,
            patch(
                "app.api.heartbeat.create_heartbeat_session_id",
                return_value="hb-session-raced",
            ),
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 409
        assert "already in progress" in response.json()["message"]
        assert response.json()["running_session_id"] == "hb-session-live"
        mock_attempt.assert_awaited_once_with(session_id="hb-session-raced")
        mock_set_running.assert_awaited_once_with(
            session_id="hb-session-raced",
            trigger="manual_api",
            project_id="persona-sandbox",
            only_if_missing=True,
        )
        mock_task.aio_run_no_wait.assert_not_called()

    def test_heartbeat_trigger_when_not_onboarded_returns_400(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
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
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.api.heartbeat.is_workflow_schedule_enabled",
                new_callable=AsyncMock,
                return_value=True,
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

    def test_heartbeat_trigger_when_paused_returns_409(self, api_client):
        with (
            patch(
                "app.api.heartbeat._get_effective_running_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.api.heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="paused",
            ),
        ):
            response = api_client.post("/api/heartbeat/trigger")

        assert response.status_code == 409
        assert response.json()["message"] == "Persona is paused"

    def test_heartbeat_trigger_rejects_unknown_target_project(self, api_client):
        with patch(
            "app.constants.VALID_PROJECT_IDS",
            frozenset({"agent-hub", "persona-sandbox"}),
        ):
            response = api_client.post("/api/heartbeat/trigger", json={"target_project_id": "unknown-project"})

        assert response.status_code == 400
        assert "Unknown target project" in response.json()["message"]
