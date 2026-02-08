
from pydantic import BaseModel


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
