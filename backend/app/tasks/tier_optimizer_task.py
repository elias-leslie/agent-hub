"""Celery task for tier optimization."""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.celery_app import celery_app
from app.config import settings

logger = logging.getLogger(__name__)

# Lock configuration
LOCK_PREFIX = "agent-hub:task-lock:"
TIER_OPTIMIZER_LOCK_TTL = 600  # 10 minutes - generous for daily job


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


@celery_app.task(name="app.tasks.tier_optimizer_task.run_tier_optimizer")
def run_tier_optimizer() -> dict[str, object]:
    """Celery task to run tier optimization.

    Runs daily at 2am UTC via celery beat.
    Promotes high-utility episodes, demotes low-utility/zombie episodes.
    Uses Redis lock to prevent duplicate execution across workers.

    Returns:
        Dict with optimization statistics
    """
    from app.services.memory.tier_optimizer import optimize_tiers

    with task_lock("tier_optimizer", TIER_OPTIMIZER_LOCK_TTL) as acquired:
        if not acquired:
            logger.info("Tier optimizer already running, skipping")
            return {"status": "skipped", "reason": "already_running"}

        result = asyncio.run(optimize_tiers())
        logger.info(
            "Tier optimization complete: %d demotions, %d promotions",
            result.get("demotions", 0),
            result.get("promotions", 0),
        )
        return {"status": "success", **result}
