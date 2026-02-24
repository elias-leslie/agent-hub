"""Health check operations for memory service.

Uses PostgreSQL connectivity check (replaces Neo4j/Graphiti health checks).
"""

import logging
from typing import Any

from sqlalchemy import text

from app.db import async_session

logger = logging.getLogger(__name__)


async def check_memory_health(
    graphiti: Any = None,
    scope_value: str = "",
    scope_id: str | None = None,
) -> dict[str, Any]:
    """
    Check memory system health by verifying PostgreSQL connectivity.

    Args:
        graphiti: Ignored (kept for backward-compat signature).
        scope_value: Memory scope value (for reporting).
        scope_id: Scope identifier (for reporting).

    Returns:
        Health status dict with database connectivity status.
    """
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
