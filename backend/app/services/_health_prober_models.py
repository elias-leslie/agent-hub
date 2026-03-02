"""Data models for health prober service."""

from dataclasses import dataclass
from enum import StrEnum


class ProviderState(StrEnum):
    """Health state of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class HealthEvent(StrEnum):
    """Events emitted on provider state changes."""

    PROVIDER_DEGRADED = "provider_degraded"
    PROVIDER_DOWN = "provider_down"
    PROVIDER_RECOVERED = "provider_recovered"


@dataclass
class ProviderHealth:
    """Health metrics for a single provider."""

    name: str
    state: ProviderState = ProviderState.UNKNOWN
    last_check: float = 0.0
    last_success: float = 0.0
    latency_ms: float = 0.0
    error_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    last_error: str | None = None

    @property
    def availability(self) -> float:
        """Calculate availability as success_rate (0.0-1.0)."""
        total = self.success_count + self.error_count
        if total == 0:
            return 1.0
        return self.success_count / total

    @property
    def error_rate(self) -> float:
        """Calculate error rate (0.0-1.0)."""
        return 1.0 - self.availability


@dataclass
class HealthProberConfig:
    """Configuration for health prober."""

    probe_interval_seconds: float = 30.0
    degraded_threshold: int = 2
    down_threshold: int = 3
    recovery_threshold: int = 2
    latency_degraded_ms: float = 5000.0
    probe_timeout_seconds: float = 10.0
    circuit_breaker_cooldown_seconds: float = 300.0  # 5 min cooldown for DOWN providers
