import logging
import time
from collections.abc import Callable
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.api.health_schemas import (
    CircuitBreakerStatus,
    ProviderHealthDetails,
    ProviderStatus,
    StatusResponse,
)
from app.services.health_prober import ProviderHealth, ProviderState

logger = logging.getLogger(__name__)


def _build_health_details(health: ProviderHealth) -> ProviderHealthDetails:
    """Convert a ProviderHealth snapshot into ProviderHealthDetails."""
    return ProviderHealthDetails(
        state=health.state.value,
        latency_ms=health.latency_ms,
        error_rate=health.error_rate,
        availability=health.availability,
        consecutive_failures=health.consecutive_failures,
        last_check=health.last_check if health.last_check > 0 else None,
        last_success=health.last_success if health.last_success > 0 else None,
        last_error=health.last_error,
    )


def _unknown_health_details() -> ProviderHealthDetails:
    """Return a placeholder ProviderHealthDetails for an uninitialised provider."""
    return ProviderHealthDetails(
        state=ProviderState.UNKNOWN.value,
        latency_ms=0.0,
        error_rate=0.0,
        availability=1.0,
        consecutive_failures=0,
        last_check=None,
        last_success=None,
        last_error=None,
    )


async def _get_provider_status(
    name: str,
    configured: bool,
    health: ProviderHealth | None,
    adapter_loader: Callable[[], ProviderAdapter],
) -> ProviderStatus:
    """Generic helper to check status of a single provider."""
    status = ProviderStatus(name=name, available=False, configured=configured)
    if not configured:
        return status

    if health and health.last_check > 0:
        status.available = health.state in (ProviderState.HEALTHY, ProviderState.DEGRADED)
        status.error = health.last_error
        status.health = _build_health_details(health)
    elif health and health.state == ProviderState.UNKNOWN and health.last_check == 0:
        # Prober hasn't completed first probe yet — assume available
        # rather than making a synchronous fallback check that can fail
        # and briefly flash "unavailable" in the UI (race condition)
        status.available = True
        status.health = _unknown_health_details()
    else:
        try:
            adapter = adapter_loader()
            status.available = await adapter.health_check()
        except Exception as e:
            status.error = str(e)[:100]

    return status


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
    try:
        from app.services.router import get_router, get_thrashing_metrics

        router_instance = get_router()
        circuit_breakers: dict[str, CircuitBreakerStatus] = {
            p: CircuitBreakerStatus(
                state=cast(str, info["state"]),
                consecutive_failures=cast(int, info["consecutive_failures"]),
                last_error_signature=cast(str | None, info["last_error_signature"]),
                cooldown_until=cast(float | None, info["cooldown_until"]),
            )
            for p, info in router_instance.get_circuit_status().items()
        }
        metrics_data = get_thrashing_metrics()
        thrashing_events: int = metrics_data["thrashing_events_total"]
        circuit_trips: int = metrics_data["circuit_breaker_trips_total"]
        return circuit_breakers, thrashing_events, circuit_trips
    except Exception as e:
        logger.warning(f"Failed to get circuit breaker status: {e}")
        return None, 0, 0


async def fetch_status(db: AsyncSession, start_time: float) -> StatusResponse:
    """Internal function to fetch fresh status data."""
    from app.adapters.registry import get_adapter
    from app.services.health_prober import get_health_prober

    db_status = await _check_database(db)

    prober = get_health_prober()
    all_health = prober.get_all_health()

    # A provider is configured if the prober has an adapter for it.
    # Adapters that can't resolve credentials fail at creation time and
    # are skipped by the prober, so presence = configured.
    providers = []
    for name, health in all_health.items():
        def _make_loader(n: str) -> Callable[[], ProviderAdapter]:
            return lambda: get_adapter(n)

        configured = name in prober._adapters
        status = await _get_provider_status(
            name, configured, health, _make_loader(name)
        )
        providers.append(status)

    circuit_breakers, thrashing_events, circuit_trips = _get_circuit_breaker_info()

    overall_status = (
        "healthy"
        if db_status == "connected" and any(p.available for p in providers)
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
