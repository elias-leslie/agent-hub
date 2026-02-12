import logging
import shutil
import time
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health_schemas import (
    CircuitBreakerStatus,
    ProviderHealthDetails,
    ProviderStatus,
    StatusResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)

async def _get_provider_status(
    name: str,
    configured: bool,
    health: Any | None,
    adapter_loader: Any,
) -> ProviderStatus:
    """Generic helper to check status of a single provider."""
    from app.services.health_prober import ProviderState

    status = ProviderStatus(name=name, available=False, configured=configured)
    if not configured:
        return status

    if health and health.last_check > 0:
        status.available = health.state in (ProviderState.HEALTHY, ProviderState.DEGRADED)
        status.error = health.last_error
        status.health = ProviderHealthDetails(
            state=health.state.value,
            latency_ms=health.latency_ms,
            error_rate=health.error_rate,
            availability=health.availability,
            consecutive_failures=health.consecutive_failures,
            last_check=health.last_check if health.last_check > 0 else None,
            last_success=health.last_success if health.last_success > 0 else None,
            last_error=health.last_error,
        )
    else:
        try:
            adapter = adapter_loader()
            status.available = await adapter.health_check()
        except Exception as e:
            status.error = str(e)[:100]

    return status

async def fetch_status(db: AsyncSession, start_time: float) -> StatusResponse:
    """Internal function to fetch fresh status data."""
    from app.services.health_prober import get_health_prober

    # Check database connection
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Database check failed: {e}")
        db_status = f"error: {str(e)[:50]}"

    # Get health prober for provider metrics
    provider_health = get_health_prober().get_all_health()

    # Define provider configurations
    def load_claude() -> Any:
        from app.adapters.claude import ClaudeAdapter
        return ClaudeAdapter()

    def load_gemini() -> Any:
        from app.adapters.gemini import GeminiAdapter
        return GeminiAdapter()

    # Check configuration via credential manager (DB) or env var fallback
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    claude_configured = (
        bool(settings.anthropic_api_key)
        or (cm.is_initialized and bool(cm.get_api_key("claude")))
        or shutil.which("claude") is not None
    )
    gemini_configured = bool(settings.gemini_api_key) or (
        cm.is_initialized and bool(cm.get_api_key("gemini"))
    )

    providers = [
        await _get_provider_status("claude", claude_configured, provider_health.get("claude"), load_claude),
        await _get_provider_status("gemini", gemini_configured, provider_health.get("gemini"), load_gemini),
    ]

    # Get circuit breaker status from router
    circuit_breakers: dict[str, CircuitBreakerStatus] | None = None
    thrashing_events = 0
    circuit_trips = 0
    try:
        from app.services.router import get_router, get_thrashing_metrics

        router_instance = get_router()
        circuit_breakers = {
            p: CircuitBreakerStatus(
                state=cast(str, info["state"]),
                consecutive_failures=cast(int, info["consecutive_failures"]),
                last_error_signature=cast(str | None, info["last_error_signature"]),
                cooldown_until=cast(float | None, info["cooldown_until"]),
            )
            for p, info in router_instance.get_circuit_status().items()
        }
        metrics_data = get_thrashing_metrics()
        thrashing_events = metrics_data["thrashing_events_total"]
        circuit_trips = metrics_data["circuit_breaker_trips_total"]
    except Exception as e:
        logger.warning(f"Failed to get circuit breaker status: {e}")

    overall_status = "healthy" if db_status == "connected" and any(p.available for p in providers) else "degraded"

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
