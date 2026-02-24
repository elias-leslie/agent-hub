"""Health check operations for memory service."""

import logging
from typing import Any

from sqlalchemy import text

from app.db import async_session

logger = logging.getLogger(__name__)


async def check_memory_health(
    scope_value: str = "",
    scope_id: str | None = None,
) -> dict[str, Any]:
    """Check memory system health by verifying PostgreSQL connectivity."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
            "scope": scope_value,
            "scope_id": scope_id,
        }
    except Exception as e:
        logger.error("Memory health check failed: %s", e)
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
        }
