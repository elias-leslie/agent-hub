"""Tests for the site health check trigger API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestSiteHealthCheckTrigger:
    """Tests for POST /api/site-health-check/trigger."""

    def test_trigger_site_health_check_dispatches_async_workflow(self, api_client) -> None:
        with patch("app.api.site_health_check.single_project_health_check_task") as mock_task:
            mock_task.aio_run_no_wait = AsyncMock()

            response = api_client.post(
                "/api/site-health-check/trigger",
                json={"project_id": "agent-hub", "task_id": "task-123"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "status": "dispatched",
            "project_id": "agent-hub",
            "message": None,
        }
        mock_task.aio_run_no_wait.assert_awaited_once()
        workflow_input = mock_task.aio_run_no_wait.call_args.kwargs["input"]
        assert workflow_input.project_id == "agent-hub"
        assert workflow_input.task_id == "task-123"

    def test_trigger_site_health_check_skips_unknown_project(self, api_client) -> None:
        response = api_client.post(
            "/api/site-health-check/trigger",
            json={"project_id": "unknown-project"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "skipped",
            "project_id": "unknown-project",
            "message": "Unknown project: unknown-project",
        }
