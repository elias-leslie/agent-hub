"""
Metrics collection for memory context injection.

Provides non-blocking asynchronous storage of injection metrics for A/B testing
and performance analysis.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert

from app.db import _get_session_factory
from app.models import MemoryInjectionMetric

logger = logging.getLogger(__name__)


@dataclass
class InjectionMetrics:
    """Captured metrics from a single context injection."""

    injection_latency_ms: int
    mandates_count: int
    guardrails_count: int
    reference_count: int
    total_tokens: int
    query: str | None = None
    variant: str = "BASELINE"
    session_id: str | None = None
    external_id: str | None = None
    project_id: str | None = None
    memories_loaded: list[str] | None = None


async def store_injection_metrics(metrics: InjectionMetrics) -> None:
    """
    Store injection metrics to PostgreSQL asynchronously.

    This function is designed to be called with asyncio.create_task() to avoid
    blocking the main request path.

    Args:
        metrics: InjectionMetrics dataclass with captured data
    """
    try:
        session_factory = _get_session_factory()

        async with session_factory() as session:
            stmt = insert(MemoryInjectionMetric).values(
                created_at=datetime.now(UTC),
                session_id=metrics.session_id,
                external_id=metrics.external_id,
                project_id=metrics.project_id,
                injection_latency_ms=metrics.injection_latency_ms,
                mandates_count=metrics.mandates_count,
                guardrails_count=metrics.guardrails_count,
                reference_count=metrics.reference_count,
                total_tokens=metrics.total_tokens,
                query=metrics.query[:500] if metrics.query else None,
                variant=metrics.variant,
                memories_loaded=metrics.memories_loaded or [],
            )
            await session.execute(stmt)
            await session.commit()

        logger.debug(
            "Stored injection metrics: variant=%s latency=%dms tokens=%d",
            metrics.variant,
            metrics.injection_latency_ms,
            metrics.total_tokens,
        )
    except Exception as e:
        # Log but don't raise - metrics storage should never fail the main request
        logger.error("Failed to store injection metrics: %s", e, exc_info=True)


def record_injection_metrics(
    metrics: InjectionMetrics,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """
    Record injection metrics non-blocking.

    Schedules the async store operation to run in the background.
    Safe to call from both sync and async contexts.

    Args:
        metrics: InjectionMetrics dataclass with captured data
        loop: Optional event loop (uses running loop if not provided)
    """
    try:
        # Get the running loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop - can't record metrics
                logger.warning("No event loop available for metrics recording")
                return

        # Schedule as a background task
        loop.create_task(store_injection_metrics(metrics))
    except Exception as e:
        logger.error("Failed to schedule metrics recording: %s", e)


async def update_citation_metrics(
    session_id: str | None = None,
    external_id: str | None = None,
    memories_cited: list[str] | None = None,
    task_succeeded: bool | None = None,
    retries: int | None = None,
) -> int:
    """
    Update citation metrics on recent injection metrics record.

    Called after LLM response to record which memories were actually cited
    and whether the task succeeded.

    Args:
        session_id: Session to find metrics for
        external_id: External ID (task ID) to find metrics for
        memories_cited: List of memory UUIDs that were cited in response
        task_succeeded: Whether the task succeeded
        retries: Number of retries for this task

    Returns:
        Number of records updated
    """
    from sqlalchemy import desc, update

    if not session_id and not external_id:
        return 0

    try:
        session_factory = _get_session_factory()

        async with session_factory() as session:
            # Find the most recent metric record for this session/external_id
            from sqlalchemy import select

            query = select(MemoryInjectionMetric).order_by(
                desc(MemoryInjectionMetric.created_at)
            )

            if session_id:
                query = query.where(MemoryInjectionMetric.session_id == session_id)
            elif external_id:
                query = query.where(MemoryInjectionMetric.external_id == external_id)

            query = query.limit(1)

            result = await session.execute(query)
            record = result.scalar_one_or_none()

            if not record:
                logger.debug("No injection metric record found to update")
                return 0

            # Update the record
            update_values: dict[str, Any] = {}
            if memories_cited is not None:
                update_values["memories_cited"] = memories_cited
            if task_succeeded is not None:
                update_values["task_succeeded"] = task_succeeded
            if retries is not None:
                update_values["retries"] = retries

            if update_values:
                stmt = (
                    update(MemoryInjectionMetric)
                    .where(MemoryInjectionMetric.id == record.id)
                    .values(**update_values)
                )
                await session.execute(stmt)
                await session.commit()
                logger.debug("Updated injection metrics with citation data")
                return 1

            return 0
    except Exception as e:
        logger.error("Failed to update citation metrics: %s", e, exc_info=True)
        return 0
