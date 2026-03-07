"""
Helper functions for metrics_collector.py.

Extracted to keep metrics_collector.py under 150 lines.
"""

import logging
from typing import Any

from sqlalchemy import desc, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.models import MemoryInjectionMetric

logger = logging.getLogger(__name__)


async def _execute_insert_with_retry(session_factory, values: dict) -> None:
    """Insert a metric record, retrying without session_id on IntegrityError."""
    async with session_factory() as session:
        try:
            stmt = insert(MemoryInjectionMetric).values(**values)
            await session.execute(stmt)
            await session.commit()
        except IntegrityError:
            # Session may not exist yet (e.g. progressive-context called before
            # session row is created). Retry without session_id.
            await session.rollback()
            values["session_id"] = None
            stmt = insert(MemoryInjectionMetric).values(**values)
            await session.execute(stmt)
            await session.commit()


async def _find_recent_metric_record(
    session,
    session_id: str | None,
    external_id: str | None,
):
    """Find the most recent injection metric record for a session or external_id."""
    query = select(MemoryInjectionMetric).order_by(desc(MemoryInjectionMetric.created_at))

    if session_id:
        query = query.where(MemoryInjectionMetric.session_id == session_id)
    elif external_id:
        query = query.where(MemoryInjectionMetric.external_id == external_id)

    query = query.limit(1)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _apply_citation_updates(
    session,
    record_id,
    memories_cited: list[str] | None,
    task_succeeded: bool | None,
) -> int:
    """Apply citation update values to a metric record. Returns 1 if updated, 0 otherwise."""
    update_values: dict[str, Any] = {}
    if memories_cited is not None:
        update_values["memories_cited"] = memories_cited
        result = await session.execute(
            select(MemoryInjectionMetric.reference_selected_uuids).where(
                MemoryInjectionMetric.id == record_id
            )
        )
        selected_reference_uuids = result.scalar_one_or_none() or []
        cited_lookup = set(memories_cited)
        update_values["reference_cited_count"] = sum(
            1 for uuid in selected_reference_uuids if uuid in cited_lookup
        )
    if task_succeeded is not None:
        update_values["task_succeeded"] = task_succeeded

    if not update_values:
        return 0

    stmt = (
        update(MemoryInjectionMetric)
        .where(MemoryInjectionMetric.id == record_id)
        .values(**update_values)
    )
    await session.execute(stmt)
    await session.commit()
    logger.debug("Updated injection metrics with citation data")
    return 1
