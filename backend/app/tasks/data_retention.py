"""Data retention cleanup for high-volume telemetry tables.

Purges old rows from high-volume observability tables using
CTE-based batch deletes to avoid long-held locks.

Retention windows:
  - request_logs:              14 days (observability only, dashboards use 7d windows)
  - usage_stats:               30 days (analytics dashboard floor; aggregates live on memories)
  - session_events:            45 days (closed sessions only; active sessions are never pruned)
  - memory_injection_metrics:  90 days (matches the max memory metrics lookback)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10_000

# Retention windows (days)
REQUEST_LOGS_RETENTION_DAYS = 14
USAGE_STATS_RETENTION_DAYS = 30
SESSION_EVENTS_RETENTION_DAYS = 45
MEMORY_INJECTION_METRICS_RETENTION_DAYS = 90


async def _delete_batch_cte(
    db: AsyncSession,
    table: str,
    where_clause: str,
    params: dict,
) -> int:
    """Delete rows in batches using a CTE. Returns total deleted."""
    total = 0
    while True:
        cursor = await db.execute(
            text(f"""
                WITH batch AS (
                    SELECT id FROM {table}
                    WHERE {where_clause}
                    LIMIT :batch_size
                )
                DELETE FROM {table}
                WHERE id IN (SELECT id FROM batch)
            """),
            {**params, "batch_size": _BATCH_SIZE},
        )
        await db.commit()
        deleted = cast(CursorResult[Any], cursor).rowcount
        total += deleted
        if deleted < _BATCH_SIZE:
            break
    return total


async def purge_old_request_logs(
    db: AsyncSession,
    retention_days: int = REQUEST_LOGS_RETENTION_DAYS,
) -> int:
    """Delete request_logs older than retention window."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    return await _delete_batch_cte(
        db,
        "request_logs",
        "created_at < :cutoff",
        {"cutoff": cutoff},
    )


async def purge_old_usage_stats(
    db: AsyncSession,
    retention_days: int = USAGE_STATS_RETENTION_DAYS,
) -> int:
    """Delete usage_stats older than retention window."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    return await _delete_batch_cte(
        db,
        "usage_stats",
        "timestamp < :cutoff",
        {"cutoff": cutoff},
    )


async def purge_old_session_events(
    db: AsyncSession,
    retention_days: int = SESSION_EVENTS_RETENTION_DAYS,
) -> int:
    """Delete session_events for closed sessions past retention.

    Safety gates:
    - Only targets closed sessions (completed or failed)
    - Never targets active sessions
    - Age is based on session.last_activity_at (not event.created_at),
      so long-running sessions don't get events pruned prematurely
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    total = 0
    while True:
        cursor = await db.execute(
            text("""
                WITH batch AS (
                    SELECT se.id
                    FROM session_events se
                    JOIN sessions s ON s.id = se.session_id
                    WHERE s.status IN ('completed', 'failed')
                      AND COALESCE(s.last_activity_at, s.updated_at) < :cutoff
                    LIMIT :batch_size
                )
                DELETE FROM session_events
                WHERE id IN (SELECT id FROM batch)
            """),
            {"cutoff": cutoff, "batch_size": _BATCH_SIZE},
        )
        await db.commit()
        deleted = cast(CursorResult[Any], cursor).rowcount
        total += deleted
        if deleted < _BATCH_SIZE:
            break
    return total


async def purge_old_memory_injection_metrics(
    db: AsyncSession,
    retention_days: int = MEMORY_INJECTION_METRICS_RETENTION_DAYS,
) -> int:
    """Delete stale memory injection metrics beyond the analytics lookback window."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    return await _delete_batch_cte(
        db,
        "memory_injection_metrics",
        "created_at < :cutoff",
        {"cutoff": cutoff},
    )


async def run_data_retention(db: AsyncSession) -> dict[str, int]:
    """Run all retention purges. Returns counts per table."""
    request_logs_deleted = await purge_old_request_logs(db)
    if request_logs_deleted:
        logger.info("Retention: purged %d request_logs rows", request_logs_deleted)

    usage_stats_deleted = await purge_old_usage_stats(db)
    if usage_stats_deleted:
        logger.info("Retention: purged %d usage_stats rows", usage_stats_deleted)

    session_events_deleted = await purge_old_session_events(db)
    if session_events_deleted:
        logger.info("Retention: purged %d session_events rows", session_events_deleted)

    memory_injection_metrics_deleted = await purge_old_memory_injection_metrics(db)
    if memory_injection_metrics_deleted:
        logger.info(
            "Retention: purged %d memory_injection_metrics rows",
            memory_injection_metrics_deleted,
        )

    return {
        "request_logs_deleted": request_logs_deleted,
        "usage_stats_deleted": usage_stats_deleted,
        "session_events_deleted": session_events_deleted,
        "memory_injection_metrics_deleted": memory_injection_metrics_deleted,
    }
