"""Data retention cleanup for high-volume telemetry tables.

Purges old rows from high-volume observability tables using
CTE-based batch deletes to avoid long-held locks.

Retention windows:
  - request_logs:              14 days (observability only, dashboards use 7d windows)
  - usage_stats:               30 days (analytics dashboard floor; aggregates live on memories)
  - memory_injection_metrics:  90 days (matches the max memory metrics lookback)

A finished session idle past settings.session_events_archive_after_days
moves its events into one compressed archive row
(app/services/session_event_archive.py); that archive is deleted once the
session has been idle past settings.session_event_archives_delete_after_days
(0 keeps it). The session row and usage_calls stay.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.session_event_archive import (
    compact_old_sessions,
    purge_expired_archives,
    vacuum_session_events,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10_000

# Retention windows (days)
REQUEST_LOGS_RETENTION_DAYS = 14
USAGE_STATS_RETENTION_DAYS = 30
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


async def archive_old_session_events(db: AsyncSession) -> dict[str, Any]:
    """Archive finished sessions idle past the window, then VACUUM so their rows' space is reused."""
    result = await compact_old_sessions(db, settings.session_events_archive_after_days)
    if result.sessions:
        try:
            await vacuum_session_events(db)
        except Exception:
            logger.exception("Retention: VACUUM session_events failed after archiving")
    return result.as_dict()


async def purge_expired_session_archives(db: AsyncSession) -> tuple[int, int]:
    """Delete session archives past the configured window; (0, 0) when the window is 0 (keep forever)."""
    days = settings.session_event_archives_delete_after_days
    if not days:
        return 0, 0
    return await purge_expired_archives(db, days)


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


async def run_data_retention(db: AsyncSession) -> dict[str, Any]:
    """Run all retention purges. Returns counts per table."""
    request_logs_deleted = await purge_old_request_logs(db)
    if request_logs_deleted:
        logger.info("Retention: purged %d request_logs rows", request_logs_deleted)

    usage_stats_deleted = await purge_old_usage_stats(db)
    if usage_stats_deleted:
        logger.info("Retention: purged %d usage_stats rows", usage_stats_deleted)

    archived = await archive_old_session_events(db)
    if archived["sessions"] or archived["failed"] or archived["skipped"]:
        logger.info(
            "Retention: archived %d sessions (%d events, %d bytes JSONL -> %d bytes stored); skipped %s; failed %s",
            archived["sessions"], archived["events"], archived["raw_bytes"], archived["stored_bytes"],
            archived["skipped"], archived["failed"],
        )

    archives_deleted, archive_bytes_deleted = await purge_expired_session_archives(db)
    if archives_deleted:
        logger.info("Retention: deleted %d session archives (%d bytes)", archives_deleted, archive_bytes_deleted)

    memory_injection_metrics_deleted = await purge_old_memory_injection_metrics(db)
    if memory_injection_metrics_deleted:
        logger.info(
            "Retention: purged %d memory_injection_metrics rows",
            memory_injection_metrics_deleted,
        )

    return {
        "request_logs_deleted": request_logs_deleted,
        "usage_stats_deleted": usage_stats_deleted,
        "sessions_archived": archived["sessions"],
        "session_events_archived": archived["events"],
        "session_events_archive_raw_bytes": archived["raw_bytes"],
        "session_events_archive_stored_bytes": archived["stored_bytes"],
        "session_archive_skipped": archived["skipped"],
        "session_archive_failed": archived["failed"],
        "session_archives_deleted": archives_deleted,
        "session_archive_bytes_deleted": archive_bytes_deleted,
        "memory_injection_metrics_deleted": memory_injection_metrics_deleted,
    }
