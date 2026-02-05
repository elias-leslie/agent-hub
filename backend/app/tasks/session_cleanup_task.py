"""Celery task for session cleanup."""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.celery_app import celery_app
from app.config import settings
from app.db import async_session
from app.tasks.session_cleanup import cleanup_stale_sessions

logger = logging.getLogger(__name__)

# Lock configuration
LOCK_PREFIX = "agent-hub:task-lock:"
SESSION_CLEANUP_LOCK_TTL = 120  # 2 minutes - enough for cleanup but short for 5min schedule


@contextmanager
def task_lock(task_name: str, ttl: int) -> Iterator[bool]:
    """Acquire a Redis lock for task deduplication.

    Args:
        task_name: Name of the task (used as lock key)
        ttl: Lock TTL in seconds

    Yields:
        True if lock acquired, False if already locked
    """
    lock_key = f"{LOCK_PREFIX}{task_name}"
    client = redis.from_url(settings.agent_hub_redis_url)
    try:
        # SET NX (only if not exists) with TTL
        acquired = client.set(lock_key, "1", nx=True, ex=ttl)
        yield bool(acquired)
    finally:
        if acquired:
            client.delete(lock_key)
        client.close()


@celery_app.task(name="app.tasks.session_cleanup_task.cleanup_stale_sessions_task")
def cleanup_stale_sessions_task() -> dict[str, object]:
    """Celery task to clean up stale sessions.

    Runs every 5 minutes via celery beat.
    Marks inactive sessions as completed based on session type timeouts.
    Uses Redis lock to prevent duplicate execution across workers.

    Returns:
        Dict with cleanup statistics
    """

    async def _run_cleanup() -> int:
        async with async_session() as db:
            return await cleanup_stale_sessions(db)

    with task_lock("session_cleanup", SESSION_CLEANUP_LOCK_TTL) as acquired:
        if not acquired:
            logger.info("Session cleanup already running, skipping")
            return {"status": "skipped", "reason": "already_running"}

        cleaned = asyncio.run(_run_cleanup())
        return {"status": "success", "sessions_cleaned": cleaned}
