"""Tests for the access-control stats query definitions.

The admin page's "Blocked Today" card reads ``blocked_requests_today``. Its
definition must match this independent SQL over request_logs:

    SELECT count(*) FROM request_logs
    WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
      AND rejection_reason IS NOT NULL;
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.api.access_control_stats import get_stats


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


@pytest.mark.asyncio
async def test_blocked_today_counts_middleware_rejections_since_utc_midnight():
    statements: list[str] = []
    # total, active, suspended, blocked clients, total today, blocked today, unknown today
    scalars = iter([10, 7, 1, 2, 500, 51, 41])

    async def execute(stmt):
        statements.append(_sql(stmt))
        result = MagicMock()
        result.scalar.return_value = next(scalars)
        return result

    db = AsyncMock()
    db.execute.side_effect = execute

    stats = await get_stats(db)

    assert stats.blocked_requests_today == 51
    assert stats.unknown_client_requests_today == 41
    assert stats.total_requests_today == 500

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    blocked_sql = statements[5]
    assert "FROM request_logs" in blocked_sql
    assert "request_logs.rejection_reason IS NOT NULL" in blocked_sql
    assert f"request_logs.created_at >= '{today} 00:00:00+00:00'" in blocked_sql
    # Endpoint-level 4xx responses are not "blocked": no status_code filter.
    assert "status_code" not in blocked_sql

    unknown_sql = statements[6]
    assert "request_logs.rejection_reason = 'client_not_found'" in unknown_sql
    assert f"request_logs.created_at >= '{today} 00:00:00+00:00'" in unknown_sql
