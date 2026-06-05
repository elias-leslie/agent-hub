"""Tests for data retention cleanup task."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.data_retention import (
    _BATCH_SIZE,
    MEMORY_INJECTION_METRICS_RETENTION_DAYS,
    REQUEST_LOGS_RETENTION_DAYS,
    SESSION_EVENTS_RETENTION_DAYS,
    USAGE_STATS_RETENTION_DAYS,
    purge_old_memory_injection_metrics,
    purge_old_request_logs,
    purge_old_session_events,
    purge_old_usage_stats,
    run_data_retention,
)


def _make_result(rowcount: int) -> MagicMock:
    r = MagicMock()
    r.rowcount = rowcount
    return r


@pytest.mark.asyncio
async def test_purge_old_request_logs_deletes_in_batches() -> None:
    db = AsyncMock()
    # First batch full, second batch partial (done)
    db.execute = AsyncMock(
        side_effect=[_make_result(10_000), _make_result(3_000)]
    )
    deleted = await purge_old_request_logs(db, retention_days=14)
    assert deleted == 13_000
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_purge_old_request_logs_no_rows() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result(0))
    deleted = await purge_old_request_logs(db, retention_days=14)
    assert deleted == 0
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_old_usage_stats_single_batch() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result(500))
    deleted = await purge_old_usage_stats(db, retention_days=30)
    assert deleted == 500
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_old_session_events_respects_safety_gates() -> None:
    """Verify the CTE joins on closed sessions and session activity age."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result(2_000))

    deleted = await purge_old_session_events(db, retention_days=45)
    assert deleted == 2_000

    # Verify the SQL contains the safety gates
    sql_arg = str(db.execute.call_args_list[0][0][0])
    assert "s.status = " in sql_arg or "status" in sql_arg
    assert "completed" in sql_arg
    assert "failed" in sql_arg
    assert "last_activity_at" in sql_arg


@pytest.mark.asyncio
async def test_purge_old_memory_injection_metrics_single_batch() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result(750))
    deleted = await purge_old_memory_injection_metrics(db, retention_days=90)
    assert deleted == 750
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_data_retention_returns_all_counts() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result(0))

    with (
        patch("app.tasks.data_retention.purge_old_request_logs", return_value=100) as mock_rl,
        patch("app.tasks.data_retention.purge_old_usage_stats", return_value=200) as mock_us,
        patch("app.tasks.data_retention.purge_old_session_events", return_value=300) as mock_se,
        patch(
            "app.tasks.data_retention.purge_old_memory_injection_metrics",
            return_value=400,
        ) as mock_mim,
    ):
        result = await run_data_retention(db)

    assert result == {
        "request_logs_deleted": 100,
        "usage_stats_deleted": 200,
        "session_events_deleted": 300,
        "memory_injection_metrics_deleted": 400,
    }
    mock_rl.assert_awaited_once_with(db)
    mock_us.assert_awaited_once_with(db)
    mock_se.assert_awaited_once_with(db)
    mock_mim.assert_awaited_once_with(db)


def test_retention_constants() -> None:
    """Verify retention windows match documented policy."""
    assert REQUEST_LOGS_RETENTION_DAYS == 14
    assert USAGE_STATS_RETENTION_DAYS == 30
    assert SESSION_EVENTS_RETENTION_DAYS == 45
    assert MEMORY_INJECTION_METRICS_RETENTION_DAYS == 90
    assert _BATCH_SIZE == 10_000
