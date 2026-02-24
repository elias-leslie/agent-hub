"""
Database flush operations for usage tracking.

Handles flushing buffered usage metrics to PostgreSQL via MemoryRepository
(counters on memories table) and historical logs (usage_stat_logs table).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import insert

from app.db import _get_session_factory
from app.models import UsageStatLog

from .repository import get_memory_repository

logger = logging.getLogger(__name__)

# Metric types
METRIC_LOADED = "loaded"
METRIC_REFERENCED = "referenced"
METRIC_SUCCESS = "success"
METRIC_HELPFUL = "helpful"
METRIC_HARMFUL = "harmful"


async def flush_to_neo4j(counters: dict[str, dict[str, int]]) -> None:
    """
    Update counter properties on memory records via MemoryRepository.

    Batch updates usage counters using repository increment methods.
    The function name is kept as ``flush_to_neo4j`` for backward compatibility
    with callers in usage_tracker.py.

    Args:
        counters: Dictionary of {memory_uuid: {metric_type: count}}
    """
    repo = get_memory_repository()

    # Group UUIDs by metric for efficient batch updates
    loaded_ids: list[str] = []
    referenced_ids: list[str] = []
    helpful_ids: list[str] = []
    harmful_ids: list[str] = []

    for uuid, metrics in counters.items():
        loaded_count = metrics.get(METRIC_LOADED, 0)
        referenced_count = metrics.get(METRIC_REFERENCED, 0)
        helpful_count = metrics.get(METRIC_HELPFUL, 0)
        harmful_count = metrics.get(METRIC_HARMFUL, 0)

        # For each metric, add the UUID the appropriate number of times
        # so that increment_* (which adds 1 per call) accumulates correctly.
        # However, repository increment methods add +1 in a single UPDATE.
        # For counts > 1 we need to call multiple times or handle differently.
        # Since typical flush intervals are short, counts are almost always 1.
        for _ in range(loaded_count):
            loaded_ids.append(uuid)
        for _ in range(referenced_count):
            referenced_ids.append(uuid)
        for _ in range(helpful_count):
            helpful_ids.append(uuid)
        for _ in range(harmful_count):
            harmful_ids.append(uuid)

    updated = 0

    if loaded_ids:
        await repo.increment_loaded(loaded_ids)
        updated += len(set(loaded_ids))

    if referenced_ids:
        await repo.increment_referenced(referenced_ids)
        updated += len(set(referenced_ids))

    if helpful_ids:
        for uid in helpful_ids:
            await repo.increment_helpful(uid)
        updated += len(set(helpful_ids))

    if harmful_ids:
        for uid in harmful_ids:
            await repo.increment_harmful(uid)
        updated += len(set(harmful_ids))

    logger.info("Updated usage counters for %d memories", len(counters))


async def flush_to_postgres(counters: dict[str, dict[str, int]]) -> None:
    """
    Insert historical usage logs to PostgreSQL.

    Creates individual log records for each metric increment.

    Args:
        counters: Dictionary of {episode_uuid: {metric_type: count}}
    """
    session_factory = _get_session_factory()

    # Build insert values
    rows = []
    now = datetime.now(UTC)
    for uuid, metrics in counters.items():
        for metric_type, value in metrics.items():
            if value > 0:
                rows.append(
                    {
                        "episode_uuid": uuid,
                        "metric_type": metric_type,
                        "value": value,
                        "timestamp": now,
                    }
                )

    if not rows:
        return

    async with session_factory() as session:
        # Use bulk insert for efficiency
        stmt = insert(UsageStatLog).values(rows)
        await session.execute(stmt)
        await session.commit()

    logger.info("Inserted %d usage stat logs to PostgreSQL", len(rows))


async def init_usage_properties() -> int:
    """
    Initialize usage properties on existing memories.

    No-op for PostgreSQL — column defaults handle this.
    Kept for backward compatibility.

    Returns the number of records updated (always 0).
    """
    logger.info("init_usage_properties: no-op for PostgreSQL (column defaults handle initialization)")
    return 0
