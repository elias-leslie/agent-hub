"""Celery task for session cleanup."""

import asyncio
import logging

from app.celery_app import celery_app
from app.db import get_db
from app.tasks.session_cleanup import cleanup_stale_sessions

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.session_cleanup_task.cleanup_stale_sessions_task")
def cleanup_stale_sessions_task() -> dict[str, object]:
    """Celery task to clean up stale sessions.

    Runs every 5 minutes via celery beat.
    Marks inactive sessions as completed based on session type timeouts.

    Returns:
        Dict with cleanup statistics
    """

    async def _run_cleanup() -> int:
        async for db in get_db():
            return await cleanup_stale_sessions(db)
        return 0

    try:
        cleaned = asyncio.run(_run_cleanup())
        return {"status": "success", "sessions_cleaned": cleaned}
    except Exception as e:
        logger.error(f"Session cleanup task failed: {e}")
        return {"status": "error", "error": str(e)}
