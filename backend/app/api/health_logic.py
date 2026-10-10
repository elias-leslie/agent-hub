import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health_schemas import (
    CircuitBreakerStatus,
    ProviderStatus,
    StatusResponse,
)

logger = logging.getLogger(__name__)


async def provider_statuses() -> list[ProviderStatus]:
    """Readiness of each routing provider, by the same check routing runs before a call.

    Agent Hub stores no runtime health metrics, so ``health`` stays empty rather
    than reporting invented latency or availability.
    """
    from app.routing.availability import provider_unavailable_reason
    from app.routing.registry import list_workload_providers

    statuses = []
    for provider in list_workload_providers():
        reason = await provider_unavailable_reason(provider)
        statuses.append(ProviderStatus(name=provider, available=reason is None, configured=reason is None, error=reason))
    return statuses


async def _check_database(db: AsyncSession) -> str:
    """Ping the database and return a status string."""
    try:
        await db.execute(text("SELECT 1"))
        return "connected"
    except Exception as e:
        logger.warning(f"Database check failed: {e}")
        return f"error: {str(e)[:50]}"



def _get_circuit_breaker_info() -> tuple[dict[str, CircuitBreakerStatus] | None, int, int]:
    """Return (circuit_breakers, thrashing_events, circuit_trips)."""
    return {}, 0, 0


async def fetch_status(db: AsyncSession, start_time: float) -> StatusResponse:
    """Internal function to fetch fresh status data."""
    db_status = await _check_database(db)
    providers = await provider_statuses()

    circuit_breakers, thrashing_events, circuit_trips = _get_circuit_breaker_info()

    overall_status = (
        "healthy"
        if db_status == "connected"
        else "degraded"
    )

    return StatusResponse(
        status=overall_status,
        service="agent-hub",
        database=db_status,
        providers=providers,
        uptime_seconds=time.time() - start_time,
        circuit_breakers=circuit_breakers,
        thrashing_events_total=thrashing_events,
        circuit_breaker_trips_total=circuit_trips,
    )
