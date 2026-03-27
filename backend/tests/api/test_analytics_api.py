"""Tests for analytics API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.analytics.models import CostLogExportRow


class TestCostLogExportEndpoint:
    """Tests for GET /api/analytics/cost-logs."""

    @pytest.mark.asyncio
    async def test_get_cost_logs_returns_cursor_payload(self, api_client) -> None:
        rows = [
            CostLogExportRow(
                id=10,
                session_id="sess-1",
                project_id="vantage",
                agent_slug="researcher",
                external_id="vantage:issue:iss-123",
                trace_id="vantage:issue:iss-123:run:run-1",
                client_id="876c5159-95c3-45fa-abbd-ac39d4d42bfc",
                request_source="vantage",
                session_type="agent",
                provider="claude",
                model="claude-sonnet-4-6",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.0123,
                created_at=datetime.now(UTC),
            )
        ]

        with patch(
            "app.api.analytics.list_cost_log_rows",
            new=AsyncMock(return_value=(rows, 10, False)),
        ) as mock_list:
            response = api_client.get("/api/analytics/cost-logs?project_id=vantage&limit=1")

        assert response.status_code == 200
        data = response.json()
        assert data["rows"][0]["project_id"] == "vantage"
        assert data["rows"][0]["trace_id"] == "vantage:issue:iss-123:run:run-1"
        assert data["next_after_id"] == 10
        assert data["has_more"] is False
        filters = mock_list.await_args.args[1]
        assert filters.project_id == "vantage"
        assert filters.limit == 1
