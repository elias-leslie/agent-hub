"""
Usage tracking service with buffered writes.

Tracks usage metrics for memory episodes:
- loaded: Episode was injected into context
- referenced: Episode was cited by LLM in response
- success: Episode was associated with positive feedback

Uses an in-memory buffer that flushes to Neo4j (counters) and PostgreSQL
(historical logs) periodically to avoid write contention.
"""

import asyncio
import contextlib
import logging
from collections import defaultdict
from threading import Lock

from .usage_flushers import (
    METRIC_HARMFUL,
    METRIC_HELPFUL,
    METRIC_LOADED,
    METRIC_REFERENCED,
    METRIC_SUCCESS,
    flush_to_neo4j,
    flush_to_postgres,
)

logger = logging.getLogger(__name__)

# Flush interval in seconds (constraint: <60s to avoid data loss)
FLUSH_INTERVAL_SECONDS = 30

# Re-export metric constants
__all__ = [
    "METRIC_HARMFUL",
    "METRIC_HELPFUL",
    "METRIC_LOADED",
    "METRIC_REFERENCED",
    "METRIC_SUCCESS",
]


class UsageBuffer:
    """Thread-safe buffer for usage metrics. Flushes to Neo4j and PostgreSQL periodically."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._flush_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._is_running = False

    def increment_loaded(self, episode_uuid: str) -> None:
        with self._lock:
            self._counters[episode_uuid][METRIC_LOADED] += 1

    def increment_referenced(self, episode_uuid: str) -> None:
        with self._lock:
            self._counters[episode_uuid][METRIC_REFERENCED] += 1

    def increment_success(self, episode_uuid: str) -> None:
        with self._lock:
            self._counters[episode_uuid][METRIC_SUCCESS] += 1

    def increment_helpful(self, episode_uuid: str) -> None:
        with self._lock:
            self._counters[episode_uuid][METRIC_HELPFUL] += 1

    def increment_harmful(self, episode_uuid: str) -> None:
        with self._lock:
            self._counters[episode_uuid][METRIC_HARMFUL] += 1

    async def flush(self) -> None:
        """Flush buffered metrics to Neo4j (counters) and PostgreSQL (logs)."""
        with self._lock:
            if not self._counters:
                return
            counters_to_flush = dict(self._counters)
            self._counters = defaultdict(lambda: defaultdict(int))

        logger.info("Flushing usage metrics for %d episodes", len(counters_to_flush))

        try:
            await flush_to_neo4j(counters_to_flush)
        except Exception as e:
            logger.error("Failed to flush to Neo4j: %s", e)
            with self._lock:
                for uuid, metrics in counters_to_flush.items():
                    for metric, count in metrics.items():
                        self._counters[uuid][metric] += count
            return

        try:
            await flush_to_postgres(counters_to_flush)
        except Exception as e:
            logger.error("Failed to flush to PostgreSQL: %s", e)

    async def start_periodic_flush(self) -> None:
        """Start background task for periodic flushing."""
        if self._is_running:
            return
        self._is_running = True
        self._shutdown_event.clear()
        self._flush_task = asyncio.create_task(self._periodic_flush_loop())
        logger.info("Started periodic usage flush (every %ds)", FLUSH_INTERVAL_SECONDS)

    async def _periodic_flush_loop(self) -> None:
        """Background loop that flushes metrics periodically."""
        while not self._shutdown_event.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=FLUSH_INTERVAL_SECONDS
                )
            if not self._shutdown_event.is_set():
                await self.flush()

    async def shutdown(self) -> None:
        """Graceful shutdown - flush remaining metrics."""
        if not self._is_running:
            return
        logger.info("Shutting down usage tracker, flushing remaining metrics...")
        self._shutdown_event.set()
        self._is_running = False
        if self._flush_task:
            try:
                await asyncio.wait_for(self._flush_task, timeout=5.0)
            except TimeoutError:
                self._flush_task.cancel()
        await self.flush()
        logger.info("Usage tracker shutdown complete")

    # Backward compatibility for tests that mock these methods
    async def _flush_to_neo4j(self, counters: dict[str, dict[str, int]]) -> None:
        """Deprecated: Use flush_to_neo4j from usage_flushers instead."""
        await flush_to_neo4j(counters)

    async def _flush_to_postgres(self, counters: dict[str, dict[str, int]]) -> None:
        """Deprecated: Use flush_to_postgres from usage_flushers instead."""
        await flush_to_postgres(counters)


_usage_buffer: UsageBuffer | None = None

def get_usage_buffer() -> UsageBuffer:
    global _usage_buffer
    if _usage_buffer is None:
        _usage_buffer = UsageBuffer()
    return _usage_buffer

async def start_usage_tracker() -> None:
    await get_usage_buffer().start_periodic_flush()

async def shutdown_usage_tracker() -> None:
    global _usage_buffer
    if _usage_buffer:
        await _usage_buffer.shutdown()
        _usage_buffer = None


def track_loaded(episode_uuid: str) -> None:
    get_usage_buffer().increment_loaded(episode_uuid)

def track_referenced(episode_uuid: str) -> None:
    get_usage_buffer().increment_referenced(episode_uuid)

def track_success(episode_uuid: str) -> None:
    get_usage_buffer().increment_success(episode_uuid)

def track_helpful(episode_uuid: str) -> None:
    get_usage_buffer().increment_helpful(episode_uuid)

def track_harmful(episode_uuid: str) -> None:
    get_usage_buffer().increment_harmful(episode_uuid)

async def track_loaded_batch(episode_uuids: list[str]) -> None:
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_loaded(uuid)

async def track_referenced_batch(episode_uuids: list[str]) -> None:
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_referenced(uuid)

async def track_success_batch(episode_uuids: list[str]) -> None:
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_success(uuid)
