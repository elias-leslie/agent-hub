"""
Health, status, and metrics endpoints.

- /health: Basic liveness check
- /status: Detailed diagnostics (providers, database)
- /metrics: Prometheus format metrics
"""

import logging
import time
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health_schemas import (
    CircuitBreakerStatus,
    HealthResponse,
    ProviderHealthDetails,
    ProviderStatus,
    StatusResponse,
)
from app.db import get_db

# Re-export schemas for backward compatibility
__all__ = [
    "CircuitBreakerStatus",
    "HealthResponse",
    "ProviderHealthDetails",
    "ProviderStatus",
    "StatusResponse",
    "router",
]

# Type alias for database dependency
DbDep = Annotated[AsyncSession, Depends(get_db)]

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Global metrics counters (simple in-memory for now)
_metrics: dict[str, Any] = {
    "request_count": 0,
    "error_count": 0,
    "active_sessions": 0,
    "latency_sum_ms": 0.0,
    "latency_count": 0,
}

# Track server start time
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic liveness check. Returns 200 OK if the service is running."""
    return HealthResponse(status="healthy", service="agent-hub")


@router.get("/status", response_model=StatusResponse)
async def status_check() -> StatusResponse:
    """Detailed diagnostics including provider and database status."""
    from app.api.health_logic import fetch_status
    from app.db import async_session
    from app.services.health_cache import get_status_cache

    cache = get_status_cache()

    async def _fetch() -> StatusResponse:
        # Use a dedicated session — the cache may call this in a background
        # task after the request-scoped session has been closed.
        async with async_session() as db:
            return await fetch_status(db, _start_time)

    result = await cache.get_or_refresh(_fetch)
    if result is None:
        raise HTTPException(status_code=503, detail="Service status unavailable")
    return cast(StatusResponse, result)


@router.get("/status/cache")
async def status_cache_info() -> dict[str, Any]:
    """Get status cache statistics."""
    from app.services.health_cache import get_status_cache
    return get_status_cache().stats


@router.get("/metrics")
async def metrics(db: DbDep) -> Response:
    """Prometheus format metrics."""
    try:
        res = await db.execute(text("SELECT COUNT(*) FROM sessions WHERE status = 'active'"))
        _metrics["active_sessions"] = res.scalar() or 0
    except Exception as e:
        logger.warning(f"Failed to get active sessions: {e}")

    thrashing_events = 0
    circuit_trips = 0
    circuit_status = {}

    from app.api.health_metrics import build_prometheus_metrics
    return build_prometheus_metrics(_metrics, _start_time, thrashing_events, circuit_trips, circuit_status)
