"""Tests for admin API schedule and hotspot endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app

TEST_HEADERS = {
    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    "X-Source-Client": "pytest",
}


@pytest.fixture
async def client():
    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac, mock_db
    app.dependency_overrides.clear()


class TestWorkflowSchedules:
    @pytest.mark.asyncio
    async def test_lists_workflow_schedules(self, client):
        ac, _ = client
        payload = [
            {
                "schedule_id": "persona_scheduler",
                "label": "Persona scheduled jobs poller",
                "description": "Polls persona jobs.",
                "cron": "*/5 * * * *",
                "category": "persona",
                "default_enabled": True,
                "enabled": False,
                "notes": None,
                "updated_by": "admin-ui",
            }
        ]
        with patch(
            "app.services.workflow_schedule_registry.list_workflow_schedule_states",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            resp = await ac.get("/api/admin/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["schedule_id"] == "persona_scheduler"
        assert data[0]["enabled"] is False

    @pytest.mark.asyncio
    async def test_updates_workflow_schedule(self, client):
        ac, mock_db = client
        payload = {
            "schedule_id": "site_health_check",
            "label": "Site health check",
            "description": "Checks sites.",
            "cron": "0 7 * * *",
            "category": "observability",
            "default_enabled": True,
            "enabled": False,
            "notes": None,
            "updated_by": "admin-ui",
        }
        with patch(
            "app.services.workflow_schedule_registry.set_workflow_schedule_enabled",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            resp = await ac.patch(
                "/api/admin/schedules/site_health_check",
                json={"enabled": False, "updated_by": "admin-ui"},
            )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_returns_404_for_unknown_schedule(self, client):
        ac, _ = client
        with patch(
            "app.services.workflow_schedule_registry.set_workflow_schedule_enabled",
            new_callable=AsyncMock,
            side_effect=KeyError("unknown"),
        ):
            resp = await ac.patch("/api/admin/schedules/nope", json={"enabled": False})
        assert resp.status_code == 404


class TestSessionHotspots:
    @pytest.mark.asyncio
    async def test_returns_session_hotspots(self, client):
        ac, _ = client
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "window_hours": 24,
            "totals": {
                "sessions": 12,
                "input_tokens": 3456,
                "output_tokens": 7890,
                "total_cost_usd": 1.2345,
                "active_sessions": 2,
                "zero_event_active_sessions": 1,
                "rate_limit_fallback_sessions": 3,
                "missing_attribution_sessions": 0,
            },
            "attribution_breakdown": [
                {
                    "kind": "autonomous",
                    "label": "Autonomous",
                    "sessions": 9,
                    "input_tokens": 3000,
                    "output_tokens": 7000,
                    "total_cost_usd": 1.1,
                }
            ],
            "repeated_workloads": [
                {
                    "workload_key": "summitflow:planner:external:task-123",
                    "label": "Fix stale planner churn",
                    "detail": "task-123",
                    "project_id": "summitflow",
                    "agent_slug": "planner",
                    "sessions": 4,
                    "input_tokens": 2000,
                    "output_tokens": 6000,
                    "total_cost_usd": 0.9,
                }
            ],
            "low_yield_sessions": [
                {
                    "session_id": "abc",
                    "project_id": "summitflow",
                    "agent_slug": "explorer",
                    "status": "completed",
                    "model": "codex/gpt-5.4",
                    "label": "Inspect browser failure",
                    "input_tokens": 9000,
                    "output_tokens": 50,
                    "total_cost_usd": 0.4,
                    "attribution_label": "Autonomous",
                    "efficiency_ratio": 180.0,
                }
            ],
            "zero_event_active_sessions": [
                {
                    "session_id": "ghost",
                    "project_id": "summitflow",
                    "agent_slug": "planner",
                    "request_source": "summitflow",
                    "quiet_for_seconds": 4200,
                    "lifecycle_state": "dead_candidate",
                }
            ],
        }
        with patch(
            "app.services.admin_session_hotspots.build_session_hotspot_snapshot",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            resp = await ac.get("/api/admin/session-hotspots?hours=24&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["rate_limit_fallback_sessions"] == 3
        assert body["repeated_workloads"][0]["project_id"] == "summitflow"
