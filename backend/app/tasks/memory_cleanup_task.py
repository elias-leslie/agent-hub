"""Celery task for weekly memory graph cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.celery_app import celery_app
from app.config import settings

logger = logging.getLogger(__name__)

LOCK_PREFIX = "agent-hub:task-lock:"
MEMORY_CLEANUP_LOCK_TTL = 300


@contextmanager
def task_lock(task_name: str, ttl: int) -> Iterator[bool]:
    lock_key = f"{LOCK_PREFIX}{task_name}"
    client = redis.from_url(settings.agent_hub_redis_url)
    acquired = False
    try:
        acquired = bool(client.set(lock_key, "1", nx=True, ex=ttl))
        yield acquired
    finally:
        if acquired:
            client.delete(lock_key)
        client.close()


@celery_app.task(name="app.tasks.memory_cleanup_task.run_memory_cleanup")
def run_memory_cleanup() -> dict[str, object]:
    """Run orphaned entity/edge cleanup and duplicate consolidation.

    Runs weekly via Celery Beat. Cleans up:
    - Orphaned edges (EntityEdge referencing deleted episodes)
    - Orphaned entities (Entity with no MENTIONS from Episodic)
    - Duplicate entities (same name, same group_id merged)
    """
    from app.services.memory.graphiti_client import get_graphiti
    from app.services.memory.service_cleanup import cleanup_orphaned

    async def _run() -> dict[str, object]:
        graphiti = get_graphiti()
        return await cleanup_orphaned(graphiti.driver, "global")

    with task_lock("memory_cleanup", MEMORY_CLEANUP_LOCK_TTL) as acquired:
        if not acquired:
            logger.info("Memory cleanup already running, skipping")
            return {"status": "skipped", "reason": "already_running"}

        result = asyncio.run(_run())
        logger.info(
            "Memory cleanup complete: edges_deleted=%d entities_deleted=%d duplicates_merged=%d",
            result.get("edges_deleted", 0),
            result.get("entities_deleted", 0),
            result.get("duplicates_merged", 0),
        )
        return {"status": "success", **result}
