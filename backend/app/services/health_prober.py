"""
Active health probing service for AI providers.

Public API — re-exports all symbols and manages the global singleton.

Implementation is split into focused modules:
- _health_prober_models: ProviderState, HealthEvent, ProviderHealth, HealthProberConfig
- _health_prober_core: HealthProber class
"""

import contextlib
from typing import Any

from ._health_prober_core import HealthProber
from ._health_prober_models import (
    HealthEvent,
    HealthProberConfig,
    ProviderHealth,
    ProviderState,
)

__all__ = [
    "HealthEvent",
    "HealthProber",
    "HealthProberConfig",
    "ProviderHealth",
    "ProviderState",
    "get_health_prober",
    "init_health_prober",
    "record_provider_failure",
    "record_provider_success",
    "shutdown_health_prober",
]

# Global singleton instance
_health_prober: HealthProber | None = None


def get_health_prober() -> HealthProber:
    """Get the global health prober instance."""
    global _health_prober
    if _health_prober is None:
        _health_prober = HealthProber()
    return _health_prober


def init_health_prober(
    config: HealthProberConfig | None = None,
    probe_providers: list[str] | None = None,
) -> HealthProber:
    """Initialize the global provider health tracker without background polling."""
    global _health_prober
    if _health_prober is not None:
        return _health_prober
    kwargs: dict[str, Any] = {"config": config or HealthProberConfig()}
    if probe_providers is not None:
        kwargs["probe_providers"] = probe_providers
    _health_prober = HealthProber(**kwargs)
    return _health_prober


def record_provider_success(provider: str, latency_ms: float) -> None:
    """Record a successful real request without forcing background probes."""
    with contextlib.suppress(Exception):
        get_health_prober().record_success(provider, latency_ms)


def record_provider_failure(
    provider: str,
    error: str,
    latency_ms: float = 0.0,
) -> None:
    """Record a failed real request without forcing background probes."""
    with contextlib.suppress(Exception):
        get_health_prober().record_failure(provider, error, latency_ms)


async def shutdown_health_prober() -> None:
    """Shutdown the global health prober."""
    global _health_prober
    if _health_prober is not None:
        await _health_prober.stop()
        _health_prober = None
