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
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

from sqlalchemy import insert

from app.db import _get_session_factory
from app.models import UsageStatLog

from .graphiti_client import get_graphiti

if TYPE_CHECKING:
    from neo4j import AsyncDriver

logger = logging.getLogger(__name__)

# Flush interval in seconds (constraint: <60s to avoid data loss)
FLUSH_INTERVAL_SECONDS = 30

# Metric types
METRIC_LOADED = "loaded"
METRIC_REFERENCED = "referenced"
METRIC_SUCCESS = "success"
METRIC_HELPFUL = "helpful"
METRIC_HARMFUL = "harmful"


class UsageBuffer:
    """
    Thread-safe in-memory buffer for usage metrics.

    Buffers metrics and flushes them periodically to Neo4j (counters)
    and PostgreSQL (historical logs).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # Counter format: {episode_uuid: {metric_type: count}}
        self._counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._flush_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._is_running = False

    def increment_loaded(self, episode_uuid: str) -> None:
        """Increment loaded counter for an episode."""
        with self._lock:
            self._counters[episode_uuid][METRIC_LOADED] += 1
        logger.debug("Incremented loaded count for %s", episode_uuid)

    def increment_referenced(self, episode_uuid: str) -> None:
        """Increment referenced counter for an episode."""
        with self._lock:
            self._counters[episode_uuid][METRIC_REFERENCED] += 1
        logger.debug("Incremented referenced count for %s", episode_uuid)

    def increment_success(self, episode_uuid: str) -> None:
        """Increment success counter for an episode."""
        with self._lock:
            self._counters[episode_uuid][METRIC_SUCCESS] += 1
        logger.debug("Incremented success count for %s", episode_uuid)

    def increment_helpful(self, episode_uuid: str) -> None:
        """Increment helpful counter for an episode (agent rated memory as helpful)."""
        with self._lock:
            self._counters[episode_uuid][METRIC_HELPFUL] += 1
        logger.debug("Incremented helpful count for %s", episode_uuid)

    def increment_harmful(self, episode_uuid: str) -> None:
        """Increment harmful counter for an episode (agent rated memory as harmful)."""
        with self._lock:
            self._counters[episode_uuid][METRIC_HARMFUL] += 1
        logger.debug("Incremented harmful count for %s", episode_uuid)

    async def flush(self) -> None:
        """
        Flush buffered metrics to Neo4j and PostgreSQL.

        Neo4j: Updates counter properties on Episodic nodes
        PostgreSQL: Inserts historical log records
        """
        # Atomically swap out the counters
        with self._lock:
            if not self._counters:
                return
            counters_to_flush = dict(self._counters)
            self._counters = defaultdict(lambda: defaultdict(int))

        logger.info("Flushing usage metrics for %d episodes", len(counters_to_flush))

        try:
            # Flush to Neo4j (counters)
            await self._flush_to_neo4j(counters_to_flush)
        except Exception as e:
            logger.error("Failed to flush to Neo4j: %s", e)
            # Re-add counters on failure
            with self._lock:
                for uuid, metrics in counters_to_flush.items():
                    for metric, count in metrics.items():
                        self._counters[uuid][metric] += count
            return

        try:
            # Flush to PostgreSQL (historical)
            await self._flush_to_postgres(counters_to_flush)
        except Exception as e:
            logger.error("Failed to flush to PostgreSQL: %s", e)
            # Neo4j was updated, log the error but don't re-add
            # PostgreSQL is for analytics, Neo4j has the source of truth

    async def _flush_to_neo4j(self, counters: dict[str, dict[str, int]]) -> None:
        """Update counter properties on Neo4j Episodic nodes."""
        from typing import cast

        graphiti = get_graphiti()
        driver: AsyncDriver = cast(AsyncDriver, graphiti.driver)

        # Batch update query with utility_score computation
        # utility_score = success_count / referenced_count (or 0 if no references)
        # helpful_count/harmful_count are ACE-aligned agent ratings
        # Note: UUID can be Episodic node, Entity node, or EntityEdge (relationship)
        # Search returns EntityEdge UUIDs - find Episodic via Entity nodes the edge connects
        query = """
        UNWIND $updates AS update
        OPTIONAL MATCH (episodic:Episodic {uuid: update.uuid})
        OPTIONAL MATCH (source1:Episodic)-[:MENTIONS]->(entity:Entity {uuid: update.uuid})
        OPTIONAL MATCH (e1:Entity)-[edge:RELATES_TO {uuid: update.uuid}]->(e2:Entity)
        OPTIONAL MATCH (source2:Episodic)-[:MENTIONS]->(e1)
        WITH update, COALESCE(episodic, source1, source2) AS e
        WHERE e IS NOT NULL
        SET e.loaded_count = COALESCE(e.loaded_count, 0) + update.loaded,
            e.referenced_count = COALESCE(e.referenced_count, 0) + update.referenced,
            e.success_count = COALESCE(e.success_count, 0) + update.success,
            e.helpful_count = COALESCE(e.helpful_count, 0) + update.helpful,
            e.harmful_count = COALESCE(e.harmful_count, 0) + update.harmful,
            e.last_used_at = datetime($now)
        WITH e
        SET e.utility_score = CASE
            WHEN (COALESCE(e.referenced_count, 0)) > 0
            THEN toFloat(COALESCE(e.success_count, 0)) / toFloat(e.referenced_count)
            ELSE 0.0
        END
        RETURN count(e) AS updated
        """

        updates = [
            {
                "uuid": uuid,
                "loaded": metrics.get(METRIC_LOADED, 0),
                "referenced": metrics.get(METRIC_REFERENCED, 0),
                "success": metrics.get(METRIC_SUCCESS, 0),
                "helpful": metrics.get(METRIC_HELPFUL, 0),
                "harmful": metrics.get(METRIC_HARMFUL, 0),
            }
            for uuid, metrics in counters.items()
        ]

        now = datetime.now(UTC).isoformat()

        records, _, _ = await driver.execute_query(query, updates=updates, now=now)

        updated_count = records[0]["updated"] if records else 0
        logger.info("Updated %d Neo4j episode nodes", updated_count)

    async def _flush_to_postgres(self, counters: dict[str, dict[str, int]]) -> None:
        """Insert historical usage logs to PostgreSQL."""
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
                    self._shutdown_event.wait(),
                    timeout=FLUSH_INTERVAL_SECONDS,
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

        # Final flush
        await self.flush()
        logger.info("Usage tracker shutdown complete")


# Global singleton instance
_usage_buffer: UsageBuffer | None = None


def get_usage_buffer() -> UsageBuffer:
    """Get the global usage buffer singleton."""
    global _usage_buffer
    if _usage_buffer is None:
        _usage_buffer = UsageBuffer()
    return _usage_buffer


async def start_usage_tracker() -> None:
    """Start the usage tracker (call on app startup)."""
    buffer = get_usage_buffer()
    await buffer.start_periodic_flush()


async def shutdown_usage_tracker() -> None:
    """Shutdown the usage tracker (call on app shutdown)."""
    buffer = get_usage_buffer()
    await buffer.shutdown()


# Convenience functions for tracking
def track_loaded(episode_uuid: str) -> None:
    """Track that an episode was loaded into context."""
    get_usage_buffer().increment_loaded(episode_uuid)


def track_referenced(episode_uuid: str) -> None:
    """Track that an episode was referenced by LLM."""
    get_usage_buffer().increment_referenced(episode_uuid)


def track_success(episode_uuid: str) -> None:
    """Track that an episode was associated with positive feedback."""
    get_usage_buffer().increment_success(episode_uuid)


def track_helpful(episode_uuid: str) -> None:
    """Track that an agent rated this episode as helpful (ACE-aligned)."""
    get_usage_buffer().increment_helpful(episode_uuid)


def track_harmful(episode_uuid: str) -> None:
    """Track that an agent rated this episode as harmful (ACE-aligned)."""
    get_usage_buffer().increment_harmful(episode_uuid)


async def track_loaded_batch(episode_uuids: list[str]) -> None:
    """Track multiple episodes loaded into context."""
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_loaded(uuid)


async def track_referenced_batch(episode_uuids: list[str]) -> None:
    """Track multiple episodes referenced by LLM."""
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_referenced(uuid)


async def track_success_batch(episode_uuids: list[str]) -> None:
    """Track multiple episodes associated with positive feedback."""
    buffer = get_usage_buffer()
    for uuid in episode_uuids:
        buffer.increment_success(uuid)


async def init_usage_properties() -> int:
    """
    Initialize usage properties on existing Episodic nodes.

    Sets default values for loaded_count, referenced_count, success_count,
    helpful_count, harmful_count, and utility_score on nodes that don't have them.

    Returns the number of nodes updated.
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    query = """
    MATCH (e:Episodic)
    WHERE e.loaded_count IS NULL
       OR e.referenced_count IS NULL
       OR e.success_count IS NULL
       OR e.helpful_count IS NULL
       OR e.harmful_count IS NULL
       OR e.utility_score IS NULL
    SET e.loaded_count = COALESCE(e.loaded_count, 0),
        e.referenced_count = COALESCE(e.referenced_count, 0),
        e.success_count = COALESCE(e.success_count, 0),
        e.helpful_count = COALESCE(e.helpful_count, 0),
        e.harmful_count = COALESCE(e.harmful_count, 0),
        e.utility_score = COALESCE(e.utility_score, 0.0)
    RETURN count(e) AS updated
    """

    records, _, _ = await driver.execute_query(query)
    updated = records[0]["updated"] if records else 0

    logger.info("Initialized usage properties on %d Episodic nodes", updated)
    return updated
