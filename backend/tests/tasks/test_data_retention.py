"""Tests for data retention cleanup task."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.session_event_archive import CompactionResult
from app.tasks.data_retention import (
    _BATCH_SIZE,
    MEMORY_INJECTION_METRICS_RETENTION_DAYS,
    REQUEST_LOGS_RETENTION_DAYS,
    USAGE_STATS_RETENTION_DAYS,
    archive_old_session_events,
    purge_old_memory_injection_metrics,
    purge_old_request_logs,
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
async def test_archive_old_session_events_uses_configured_window_and_vacuums_after_work() -> None:
    db = AsyncMock()
    archived = CompactionResult(sessions=2, events=40, raw_bytes=9000, stored_bytes=900)
    with (
        patch("app.tasks.data_retention.settings.session_events_archive_after_days", 90),
        patch("app.tasks.data_retention.compact_old_sessions", return_value=archived) as compact,
        patch("app.tasks.data_retention.vacuum_session_events") as vacuum,
    ):
        result = await archive_old_session_events(db)

    compact.assert_awaited_once_with(db, 90)
    vacuum.assert_awaited_once_with(db)
    assert result["sessions"] == 2 and result["stored_bytes"] == 900

    with (
        patch("app.tasks.data_retention.compact_old_sessions", return_value=CompactionResult()),
        patch("app.tasks.data_retention.vacuum_session_events") as vacuum,
    ):
        await archive_old_session_events(db)
    vacuum.assert_not_awaited()


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
        patch(
            "app.tasks.data_retention.archive_old_session_events",
            return_value=CompactionResult(sessions=3, events=300, raw_bytes=10, stored_bytes=1).as_dict(),
        ) as mock_se,
        patch(
            "app.tasks.data_retention.purge_old_memory_injection_metrics",
            return_value=400,
        ) as mock_mim,
    ):
        result = await run_data_retention(db)

    assert result == {
        "request_logs_deleted": 100,
        "usage_stats_deleted": 200,
        "sessions_archived": 3,
        "session_events_archived": 300,
        "session_events_archive_raw_bytes": 10,
        "session_events_archive_stored_bytes": 1,
        "session_archive_skipped": [],
        "session_archive_failed": [],
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
    assert MEMORY_INJECTION_METRICS_RETENTION_DAYS == 90
    assert _BATCH_SIZE == 10_000
