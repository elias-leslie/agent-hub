"""Session summary Celery task with Redis locking."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

SUMMARY_LOCK_TTL = 300  # 5 minutes


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
)
def generate_session_summary_task(self: Any, session_id: str) -> dict[str, object]:
    """Generate a session summary asynchronously via Celery.

    Uses Redis lock to prevent duplicate summary generation for the same session.
    Wraps the existing summary_generator.generate_session_summary() function.

    Args:
        session_id: The session UUID to summarize.

    Returns:
        Dict with summary result or skip reason.
    """
    import asyncio

    from redis import Redis

    from app.config import settings

    lock_key = f"summary_lock:{session_id}"

    redis_client = Redis.from_url(settings.celery_broker_url)
    lock = redis_client.lock(lock_key, timeout=SUMMARY_LOCK_TTL)

    if not lock.acquire(blocking=False):
        logger.info("Summary already in progress for session %s, skipping", session_id)
        return {"status": "skipped", "reason": "lock_held", "session_id": session_id}

    try:
        from app.services.memory.summary_generator import generate_session_summary

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(generate_session_summary(session_id))
        finally:
            loop.close()

        logger.info(
            "Session summary generated for %s: uuid=%s",
            session_id,
            result.episode_uuid,
        )
        return {
            "status": "success",
            "session_id": session_id,
            "episode_uuid": result.episode_uuid,
            "summary": result.summary[:200],
        }
    except ValueError as e:
        logger.warning("Cannot summarize session %s: %s", session_id, e)
        return {"status": "skipped", "reason": str(e), "session_id": session_id}
    except Exception as e:
        logger.error("Summary generation failed for session %s: %s", session_id, e)
        raise
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            lock.release()
        redis_client.close()
