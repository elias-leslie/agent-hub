"""Health check operations for memory service."""

import logging
from typing import Any, cast

from graphiti_core import Graphiti
from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


async def check_memory_health(
    graphiti: Graphiti,
    scope_value: str,
    scope_id: str | None,
) -> dict[str, Any]:
    """
    Check memory system health.

    Args:
        graphiti: Graphiti client instance
        scope_value: Memory scope value (for reporting)
        scope_id: Scope identifier (for reporting)

    Returns:
        Health status dict with neo4j and graphiti status
    """
    try:
        # Test Neo4j connection - verify_connectivity raises on failure, returns None on success
        driver = cast(AsyncDriver, graphiti.driver)
        await driver.verify_connectivity()

        return {
            "status": "healthy",
            "neo4j": "connected",
            "scope": scope_value,
            "scope_id": scope_id,
        }
    except Exception as e:
        logger.error("Memory health check failed: %s", e)
        return {
            "status": "unhealthy",
            "neo4j": "disconnected",
            "error": str(e),
        }
