"""Async observation processing via Celery."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

OBSERVATION_LOCK_TTL = 300  # 5 minutes


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
)
def process_observation_task(
    self: Any,
    request_dict: dict[str, Any],
    scope: str,
    scope_id: str | None,
) -> dict[str, object]:
    """Process an observation asynchronously via Celery.

    Deserializes the ObservationRequest and calls the existing capture logic.
    Uses Redis lock on content hash to prevent duplicate processing.

    Args:
        request_dict: Serialized ObservationRequest as dict.
        scope: Memory scope string (e.g., "global", "project").
        scope_id: Scope ID for project-scoped observations.

    Returns:
        Dict with processing result.
    """
    import asyncio
    import hashlib

    from redis import Redis

    from app.config import settings

    content_hash = hashlib.sha256(
        (request_dict.get("content", "") + request_dict.get("title", "")).encode()
    ).hexdigest()[:16]
    lock_key = f"obs_lock:{content_hash}"

    redis_client = Redis.from_url(settings.celery_broker_url)
    lock = redis_client.lock(lock_key, timeout=OBSERVATION_LOCK_TTL)

    if not lock.acquire(blocking=False):
        logger.info("Observation already being processed (hash=%s), skipping", content_hash)
        return {"status": "skipped", "reason": "duplicate_lock"}

    try:
        from app.services.memory.observation_schema import ObservationRequest
        from app.services.memory.service import MemoryScope

        request = ObservationRequest(**request_dict)
        mem_scope = MemoryScope(scope)

        from app.services.memory.capture_handler import capture_observation

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(capture_observation(request, mem_scope, scope_id))
        finally:
            loop.close()

        logger.info("Observation processed: uuid=%s stored=%s", result.uuid, result.stored)
        return {
            "status": "success",
            "uuid": result.uuid,
            "stored": result.stored,
        }
    except Exception as e:
        logger.error("Observation processing failed: %s", e)
        raise
    finally:
        with contextlib.suppress(Exception):
            lock.release()
        redis_client.close()
