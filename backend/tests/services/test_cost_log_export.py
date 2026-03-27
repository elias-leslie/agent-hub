"""Tests for raw cost-log export helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.analytics.cost_queries import list_cost_log_rows
from app.services.analytics.models import CostLogExportFilters


@pytest.mark.asyncio
async def test_list_cost_log_rows_returns_cursor_page_with_trace_ids() -> None:
    now = datetime.now(UTC)
    row_1 = SimpleNamespace(
        id=10,
        session_id="sess-1",
        project_id="vantage",
        agent_slug="researcher",
        external_id="vantage:issue:iss-123",
        provider_metadata={"trace_id": "vantage:issue:iss-123:run:run-1"},
        client_id="876c5159-95c3-45fa-abbd-ac39d4d42bfc",
        request_source="vantage",
        session_type="agent",
        provider="claude",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0123,
        created_at=now,
    )
    row_2 = SimpleNamespace(
        id=11,
        session_id="sess-2",
        project_id="vantage",
        agent_slug="researcher",
        external_id="vantage:issue:iss-124",
        provider_metadata={},
        client_id="876c5159-95c3-45fa-abbd-ac39d4d42bfc",
        request_source="vantage",
        session_type="agent",
        provider="claude",
        model="claude-sonnet-4-6",
        input_tokens=120,
        output_tokens=60,
        cost_usd=0.015,
        created_at=now,
    )
    row_3 = SimpleNamespace(
        id=12,
        session_id="sess-3",
        project_id="vantage",
        agent_slug="researcher",
        external_id="vantage:issue:iss-125",
        provider_metadata={"trace_id": "vantage:issue:iss-125:run:run-3"},
        client_id="876c5159-95c3-45fa-abbd-ac39d4d42bfc",
        request_source="vantage",
        session_type="agent",
        provider="claude",
        model="claude-sonnet-4-6",
        input_tokens=140,
        output_tokens=70,
        cost_usd=0.02,
        created_at=now,
    )

    result = MagicMock()
    result.all.return_value = [row_1, row_2, row_3]
    db = AsyncMock()
    db.execute.return_value = result

    rows, next_after_id, has_more = await list_cost_log_rows(
        db,
        CostLogExportFilters(project_id="vantage", after_id=9, limit=2),
    )

    assert len(rows) == 2
    assert rows[0].id == 10
    assert rows[0].trace_id == "vantage:issue:iss-123:run:run-1"
    assert rows[1].id == 11
    assert rows[1].trace_id is None
    assert next_after_id == 11
    assert has_more is True
    db.execute.assert_awaited_once()
