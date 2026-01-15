"""
Health, status, and metrics endpoints.

- /health: Basic liveness check
- /status: Detailed diagnostics (providers, database)
- /metrics: Prometheus format metrics
"""

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

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


class HealthResponse(BaseModel):
    """Basic health check response."""

    status: str
    service: str


class ProviderHealthDetails(BaseModel):
    """Detailed health metrics for a provider."""

    state: str
    latency_ms: float
    error_rate: float
    availability: float
    consecutive_failures: int
    last_check: float | None = None
    last_success: float | None = None
    last_error: str | None = None


class ProviderStatus(BaseModel):
    """Status of an AI provider."""

    name: str
    available: bool
    configured: bool
    error: str | None = None
    health: ProviderHealthDetails | None = None


class CircuitBreakerStatus(BaseModel):
    """Status of a circuit breaker."""

    state: str
    consecutive_failures: int
    last_error_signature: str | None = None
    cooldown_until: float | None = None


class StatusResponse(BaseModel):
    """Detailed status response."""

    status: str
    service: str
    database: str
    providers: list[ProviderStatus]
    uptime_seconds: float
    circuit_breakers: dict[str, CircuitBreakerStatus] | None = None
    thrashing_events_total: int = 0
    circuit_breaker_trips_total: int = 0


# Track server start time
_start_time = time.time()


def increment_request_count() -> None:
    """Increment the global request counter."""
    _metrics["request_count"] += 1


def increment_error_count() -> None:
    """Increment the global error counter."""
    _metrics["error_count"] += 1


def record_latency(latency_ms: float) -> None:
    """Record a request latency for histogram."""
    _metrics["latency_sum_ms"] += latency_ms
    _metrics["latency_count"] += 1


def set_active_sessions(count: int) -> None:
    """Set the number of active sessions."""
    _metrics["active_sessions"] = count


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Basic liveness check.

    Returns 200 OK if the service is running.
    """
    return HealthResponse(status="healthy", service="agent-hub")


@router.get("/status", response_model=StatusResponse)
async def status_check(db: DbDep) -> StatusResponse:
    """
    Detailed diagnostics including provider and database status.

    Uses health prober for real-time provider health metrics when available.
    """
    from app.services.health_prober import ProviderState, get_health_prober

    # Check database connection
    db_status = "unknown"
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.warning(f"Database check failed: {e}")
        db_status = f"error: {str(e)[:50]}"

    # Get health prober for provider metrics
    prober = get_health_prober()
    provider_health = prober.get_all_health()

    # Check providers
    providers: list[ProviderStatus] = []

    # Claude provider - supports OAuth via CLI OR API key
    import shutil

    claude_cli_available = shutil.which("claude") is not None
    claude_configured = bool(settings.anthropic_api_key) or claude_cli_available
    claude_health = provider_health.get("claude")
    claude_status = ProviderStatus(
        name="claude",
        available=False,
        configured=claude_configured,
    )
    if claude_configured:
        if claude_health and claude_health.last_check > 0:
            claude_status.available = claude_health.state in (
                ProviderState.HEALTHY,
                ProviderState.DEGRADED,
            )
            claude_status.error = claude_health.last_error
            claude_status.health = ProviderHealthDetails(
                state=claude_health.state.value,
                latency_ms=claude_health.latency_ms,
                error_rate=claude_health.error_rate,
                availability=claude_health.availability,
                consecutive_failures=claude_health.consecutive_failures,
                last_check=claude_health.last_check if claude_health.last_check > 0 else None,
                last_success=claude_health.last_success if claude_health.last_success > 0 else None,
                last_error=claude_health.last_error,
            )
        else:
            try:
                from app.adapters.claude import ClaudeAdapter

                adapter = ClaudeAdapter()
                claude_status.available = await adapter.health_check()
            except Exception as e:
                claude_status.error = str(e)[:100]
    providers.append(claude_status)

    # Gemini provider
    gemini_configured = bool(settings.gemini_api_key)
    gemini_health = provider_health.get("gemini")
    gemini_status = ProviderStatus(
        name="gemini",
        available=False,
        configured=gemini_configured,
    )
    if gemini_configured:
        if gemini_health and gemini_health.last_check > 0:
            gemini_status.available = gemini_health.state in (
                ProviderState.HEALTHY,
                ProviderState.DEGRADED,
            )
            gemini_status.error = gemini_health.last_error
            gemini_status.health = ProviderHealthDetails(
                state=gemini_health.state.value,
                latency_ms=gemini_health.latency_ms,
                error_rate=gemini_health.error_rate,
                availability=gemini_health.availability,
                consecutive_failures=gemini_health.consecutive_failures,
                last_check=gemini_health.last_check if gemini_health.last_check > 0 else None,
                last_success=gemini_health.last_success if gemini_health.last_success > 0 else None,
                last_error=gemini_health.last_error,
            )
        else:
            try:
                from app.adapters.gemini import GeminiAdapter

                adapter = GeminiAdapter()
                gemini_status.available = await adapter.health_check()
            except Exception as e:
                gemini_status.error = str(e)[:100]
    providers.append(gemini_status)

    # Get circuit breaker status from router
    circuit_breakers: dict[str, CircuitBreakerStatus] | None = None
    thrashing_events = 0
    circuit_trips = 0
    try:
        from app.services.router import get_router, get_thrashing_metrics

        router_instance = get_router()
        circuit_status = router_instance.get_circuit_status()
        circuit_breakers = {
            provider: CircuitBreakerStatus(
                state=info["state"],
                consecutive_failures=info["consecutive_failures"],
                last_error_signature=info["last_error_signature"],
                cooldown_until=info["cooldown_until"],
            )
            for provider, info in circuit_status.items()
        }
        metrics_data = get_thrashing_metrics()
        thrashing_events = metrics_data["thrashing_events_total"]
        circuit_trips = metrics_data["circuit_breaker_trips_total"]
    except Exception as e:
        logger.warning(f"Failed to get circuit breaker status: {e}")

    # Determine overall status
    any_provider_available = any(p.available for p in providers)
    overall_status = (
        "healthy" if db_status == "connected" and any_provider_available else "degraded"
    )

    return StatusResponse(
        status=overall_status,
        service="agent-hub",
        database=db_status,
        providers=providers,
        uptime_seconds=time.time() - _start_time,
        circuit_breakers=circuit_breakers,
        thrashing_events_total=thrashing_events,
        circuit_breaker_trips_total=circuit_trips,
    )


@router.get("/metrics")
async def metrics(db: DbDep) -> Response:
    """
    Prometheus format metrics.

    Returns metrics in Prometheus text exposition format.
    """
    # Get active session count from database
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM sessions WHERE status = 'active'"))
        active_sessions = result.scalar() or 0
        _metrics["active_sessions"] = active_sessions
    except Exception as e:
        logger.warning(f"Failed to get active sessions: {e}")

    # Get thrashing metrics
    thrashing_events = 0
    circuit_trips = 0
    circuit_state_lines: list[str] = []
    try:
        from app.services.router import get_router, get_thrashing_metrics

        metrics_data = get_thrashing_metrics()
        thrashing_events = metrics_data["thrashing_events_total"]
        circuit_trips = metrics_data["circuit_breaker_trips_total"]

        router_instance = get_router()
        circuit_status = router_instance.get_circuit_status()
        for provider, info in circuit_status.items():
            # Map state to numeric value for Prometheus (0=closed, 1=half_open, 2=open)
            state_val = {"closed": 0, "half_open": 1, "open": 2}.get(info["state"], -1)
            circuit_state_lines.append(
                f'agent_hub_circuit_state{{provider="{provider}"}} {state_val}'
            )
    except Exception as e:
        logger.warning(f"Failed to get thrashing metrics: {e}")

    # Build Prometheus format output
    lines = [
        "# HELP agent_hub_requests_total Total number of requests",
        "# TYPE agent_hub_requests_total counter",
        f"agent_hub_requests_total {_metrics['request_count']}",
        "",
        "# HELP agent_hub_errors_total Total number of errors",
        "# TYPE agent_hub_errors_total counter",
        f"agent_hub_errors_total {_metrics['error_count']}",
        "",
        "# HELP agent_hub_active_sessions Number of active sessions",
        "# TYPE agent_hub_active_sessions gauge",
        f"agent_hub_active_sessions {_metrics['active_sessions']}",
        "",
        "# HELP agent_hub_request_latency_ms Request latency histogram",
        "# TYPE agent_hub_request_latency_ms summary",
        f"agent_hub_request_latency_ms_sum {_metrics['latency_sum_ms']}",
        f"agent_hub_request_latency_ms_count {_metrics['latency_count']}",
        "",
        "# HELP agent_hub_uptime_seconds Service uptime in seconds",
        "# TYPE agent_hub_uptime_seconds gauge",
        f"agent_hub_uptime_seconds {time.time() - _start_time:.1f}",
        "",
        "# HELP agent_hub_thrashing_events_total Total thrashing detection events",
        "# TYPE agent_hub_thrashing_events_total counter",
        f"agent_hub_thrashing_events_total {thrashing_events}",
        "",
        "# HELP agent_hub_circuit_breaker_trips_total Total circuit breaker trips",
        "# TYPE agent_hub_circuit_breaker_trips_total counter",
        f"agent_hub_circuit_breaker_trips_total {circuit_trips}",
        "",
        "# HELP agent_hub_circuit_state Circuit breaker state (0=closed, 1=half_open, 2=open)",
        "# TYPE agent_hub_circuit_state gauge",
        *circuit_state_lines,
        "",
    ]

    return Response(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
