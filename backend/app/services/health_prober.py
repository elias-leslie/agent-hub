"""
Active health probing service for AI providers.

Continuously monitors provider health in background, emitting events on state changes.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from app.adapters.base import ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

logger = logging.getLogger(__name__)


class ProviderState(str, Enum):
    """Health state of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class HealthEvent(str, Enum):
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


@dataclass
class HealthProber:
    """
    Active health prober for AI providers.

    Probes each configured provider at regular intervals and tracks:
    - Latency
    - Error rate
    - Availability

    Emits events on state changes: provider_degraded, provider_down, provider_recovered.
    """

    config: HealthProberConfig = field(default_factory=HealthProberConfig)
    _providers: dict[str, ProviderHealth] = field(default_factory=dict)
    _adapters: dict[str, ProviderAdapter] = field(default_factory=dict)
    _event_handlers: list[Callable[[HealthEvent, str, ProviderHealth], None]] = field(
        default_factory=list
    )
    _running: bool = False
    _probe_task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        self._adapters = {
            "claude": ClaudeAdapter(),
            "gemini": GeminiAdapter(),
        }
        for name in self._adapters:
            self._providers[name] = ProviderHealth(name=name)

    def add_event_handler(
        self, handler: Callable[[HealthEvent, str, ProviderHealth], None]
    ) -> None:
        """Add handler for health events."""
        self._event_handlers.append(handler)

    def remove_event_handler(
        self, handler: Callable[[HealthEvent, str, ProviderHealth], None]
    ) -> None:
        """Remove handler for health events."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event: HealthEvent, provider: str) -> None:
        """Emit a health event to all handlers."""
        health = self._providers.get(provider)
        if not health:
            return
        logger.info(f"Health event: {event.value} for {provider}")
        for handler in self._event_handlers:
            try:
                handler(event, provider, health)
            except Exception as e:
                logger.error(f"Error in health event handler: {e}")

    async def _probe_provider(self, name: str) -> None:
        """Probe a single provider and update its health metrics."""
        adapter = self._adapters.get(name)
        health = self._providers.get(name)
        if not adapter or not health:
            return

        old_state = health.state
        start_time = time.monotonic()

        try:
            available = await adapter.health_check()
            latency_ms = (time.monotonic() - start_time) * 1000

            health.last_check = time.time()
            health.latency_ms = latency_ms
            health.last_error = None

            if available:
                health.success_count += 1
                health.last_success = time.time()
                consecutive_successes = health.consecutive_failures
                health.consecutive_failures = 0

                if latency_ms > self.config.latency_degraded_ms:
                    health.state = ProviderState.DEGRADED
                else:
                    health.state = ProviderState.HEALTHY

                if (
                    old_state in (ProviderState.DOWN, ProviderState.DEGRADED)
                    and health.state == ProviderState.HEALTHY
                    and consecutive_successes >= self.config.recovery_threshold - 1
                ):
                    self._emit_event(HealthEvent.PROVIDER_RECOVERED, name)
            else:
                health.error_count += 1
                health.consecutive_failures += 1
                health.last_error = "Health check returned false"
                self._update_state_on_failure(name, old_state)

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            health.last_check = time.time()
            health.latency_ms = latency_ms
            health.error_count += 1
            health.consecutive_failures += 1
            health.last_error = str(e)[:200]
            self._update_state_on_failure(name, old_state)

    def _update_state_on_failure(self, name: str, old_state: ProviderState) -> None:
        """Update provider state after a failure."""
        health = self._providers.get(name)
        if not health:
            return

        if health.consecutive_failures >= self.config.down_threshold:
            health.state = ProviderState.DOWN
            if old_state != ProviderState.DOWN:
                self._emit_event(HealthEvent.PROVIDER_DOWN, name)
        elif health.consecutive_failures >= self.config.degraded_threshold:
            health.state = ProviderState.DEGRADED
            if old_state == ProviderState.HEALTHY:
                self._emit_event(HealthEvent.PROVIDER_DEGRADED, name)

    async def _probe_loop(self) -> None:
        """Main probe loop that runs in background."""
        while self._running:
            probe_tasks = [self._probe_provider(name) for name in self._adapters]
            await asyncio.gather(*probe_tasks, return_exceptions=True)
            await asyncio.sleep(self.config.probe_interval_seconds)

    def start(self) -> None:
        """Start the background health probing."""
        if self._running:
            return
        self._running = True
        self._probe_task = asyncio.create_task(self._probe_loop())
        logger.info(f"Health prober started (interval: {self.config.probe_interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the background health probing."""
        if not self._running:
            return
        self._running = False
        if self._probe_task:
            self._probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._probe_task
            self._probe_task = None
        logger.info("Health prober stopped")

    def get_health(self, provider: str) -> ProviderHealth | None:
        """Get current health metrics for a provider."""
        return self._providers.get(provider)

    def get_all_health(self) -> dict[str, ProviderHealth]:
        """Get health metrics for all providers."""
        return dict(self._providers)

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is available (healthy or degraded)."""
        health = self._providers.get(provider)
        if not health:
            return False
        return health.state in (ProviderState.HEALTHY, ProviderState.DEGRADED)

    def get_available_providers(self) -> list[str]:
        """Get list of available providers."""
        return [
            name
            for name, health in self._providers.items()
            if health.state in (ProviderState.HEALTHY, ProviderState.DEGRADED)
        ]

    async def probe_now(self, provider: str | None = None) -> None:
        """Trigger immediate probe for one or all providers."""
        if provider:
            await self._probe_provider(provider)
        else:
            probe_tasks = [self._probe_provider(name) for name in self._adapters]
            await asyncio.gather(*probe_tasks, return_exceptions=True)


# Global singleton instance
_health_prober: HealthProber | None = None


def get_health_prober() -> HealthProber:
    """Get the global health prober instance."""
    global _health_prober
    if _health_prober is None:
        _health_prober = HealthProber()
    return _health_prober


def init_health_prober(config: HealthProberConfig | None = None) -> HealthProber:
    """Initialize and start the global health prober."""
    global _health_prober
    if _health_prober is not None:
        return _health_prober
    _health_prober = HealthProber(config=config or HealthProberConfig())
    _health_prober.start()
    return _health_prober


async def shutdown_health_prober() -> None:
    """Shutdown the global health prober."""
    global _health_prober
    if _health_prober is not None:
        await _health_prober.stop()
        _health_prober = None
