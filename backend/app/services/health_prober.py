"""
Active health probing service for AI providers.

Public API — re-exports all symbols and manages the global singleton.

Implementation is split into focused modules:
- _health_prober_models: ProviderState, HealthEvent, ProviderHealth, HealthProberConfig
- _health_prober_core: HealthProber class
"""

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
    """Initialize and start the global health prober."""
    global _health_prober
    if _health_prober is not None:
        return _health_prober
    kwargs: dict[str, Any] = {"config": config or HealthProberConfig()}
    if probe_providers is not None:
        kwargs["probe_providers"] = probe_providers
    _health_prober = HealthProber(**kwargs)
    _health_prober.start()
    return _health_prober


async def shutdown_health_prober() -> None:
    """Shutdown the global health prober."""
    global _health_prober
    if _health_prober is not None:
        await _health_prober.stop()
        _health_prober = None
