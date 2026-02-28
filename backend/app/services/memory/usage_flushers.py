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


def _build_metric_id_lists(
    counters: dict[str, dict[str, int]],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """
    Build per-metric UUID lists from counter data.

    Each UUID is repeated by its count so that per-call increment
    methods accumulate the correct total.

    Returns:
        Tuple of (loaded_ids, referenced_ids, helpful_ids, harmful_ids)
    """
    loaded_ids: list[str] = []
    referenced_ids: list[str] = []
    helpful_ids: list[str] = []
    harmful_ids: list[str] = []

    for uuid, metrics in counters.items():
        loaded_ids.extend([uuid] * metrics.get(METRIC_LOADED, 0))
        referenced_ids.extend([uuid] * metrics.get(METRIC_REFERENCED, 0))
        helpful_ids.extend([uuid] * metrics.get(METRIC_HELPFUL, 0))
        harmful_ids.extend([uuid] * metrics.get(METRIC_HARMFUL, 0))

    return loaded_ids, referenced_ids, helpful_ids, harmful_ids


async def flush_counters(counters: dict[str, dict[str, int]]) -> None:
    """
    Update counter properties on memory records via MemoryRepository.

    Batch updates usage counters using repository increment methods.

    Args:
        counters: Dictionary of {memory_uuid: {metric_type: count}}
    """
    repo = get_memory_repository()

    loaded_ids, referenced_ids, helpful_ids, harmful_ids = _build_metric_id_lists(counters)

    if loaded_ids:
        await repo.increment_loaded(loaded_ids)

    if referenced_ids:
        await repo.increment_referenced(referenced_ids)

    if helpful_ids:
        for uid in helpful_ids:
            await repo.increment_helpful(uid)

    if harmful_ids:
        for uid in harmful_ids:
            await repo.increment_harmful(uid)

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
    logger.info(
        "init_usage_properties: no-op for PostgreSQL (column defaults handle initialization)"
    )
    return 0
