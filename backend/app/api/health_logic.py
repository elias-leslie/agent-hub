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


async def check_provider_health(_api: str) -> bool:
    """Return passive OK for registered pi-mono providers.

    The legacy active prober belonged to the retired text-adapter subsystem.
    Provider calls now fail at request time through the unified stream surface.
    """
    return True


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
    from app.llm.api_registry import get_api_providers

    db_status = await _check_database(db)

    providers = [
        ProviderStatus(
            name=str(provider.api),
            available=await check_provider_health(str(provider.api)),
            configured=True,
        )
        for provider in get_api_providers()
    ]

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
