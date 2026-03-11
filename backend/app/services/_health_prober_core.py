"""
Core HealthProber class implementation.

Probes each configured provider at regular intervals and tracks latency,
error rate, and availability. Emits events on state changes.

Circuit breaker: providers in DOWN state are skipped until cooldown expires,
preventing wasted probe cycles against unresponsive/rate-limited providers.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.adapters.base import ProviderAdapter

from ._health_prober_models import (
    HealthEvent,
    HealthProberConfig,
    ProviderHealth,
    ProviderState,
)

logger = logging.getLogger(__name__)


@dataclass
class HealthProber:
    """Active health prober for AI providers."""

    config: HealthProberConfig = field(default_factory=HealthProberConfig)
    _providers: dict[str, ProviderHealth] = field(default_factory=dict)
    _adapters: dict[str, ProviderAdapter] = field(default_factory=dict)
    _event_handlers: list[Callable[[HealthEvent, str, ProviderHealth], None]] = field(
        default_factory=list
    )
    _running: bool = False
    _probe_task: asyncio.Task[None] | None = None
    _probe_providers: list[str] | None = field(default=None)

    def __post_init__(self) -> None:
        from app.adapters.registry import get_adapter, list_providers

        providers_to_probe = self._probe_providers or list_providers()
        for name in providers_to_probe:
            self._providers[name] = ProviderHealth(name=name)
            try:
                self._adapters[name] = get_adapter(name)
            except Exception:
                logger.debug(
                    "Health prober: adapter for %s not resolvable at init "
                    "(will retry each probe cycle)",
                    name,
                )

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

    def _should_skip_probe(self, name: str) -> bool:
        """Circuit breaker: skip probing DOWN providers until cooldown expires."""
        health = self._providers.get(name)
        if not health:
            return True
        if health.state != ProviderState.DOWN:
            return False
        elapsed = time.time() - health.last_check
        if elapsed < self.config.circuit_breaker_cooldown_seconds:
            return True
        logger.info(
            "Circuit breaker: cooldown expired for %s (%.0fs), allowing recovery probe",
            name, elapsed,
        )
        return False

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

    def record_success(self, name: str, latency_ms: float) -> None:
        """Record a successful real request for a provider."""
        health = self._providers.get(name)
        if not health:
            return

        old_state = health.state
        prev_failures = health.consecutive_failures
        now = time.time()
        health.last_check = now
        health.last_success = now
        health.latency_ms = latency_ms
        health.last_error = None
        health.success_count += 1
        health.consecutive_failures = 0
        health.state = (
            ProviderState.DEGRADED
            if latency_ms > self.config.latency_degraded_ms
            else ProviderState.HEALTHY
        )
        if (
            old_state in (ProviderState.DOWN, ProviderState.DEGRADED)
            and health.state == ProviderState.HEALTHY
            and prev_failures >= self.config.recovery_threshold - 1
        ):
            self._emit_event(HealthEvent.PROVIDER_RECOVERED, name)

    def record_failure(
        self,
        name: str,
        error: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a failed real request for a provider."""
        health = self._providers.get(name)
        if not health:
            return

        old_state = health.state
        health.last_check = time.time()
        health.latency_ms = latency_ms
        health.error_count += 1
        health.consecutive_failures += 1
        health.last_error = error[:200]
        self._update_state_on_failure(name, old_state)

    async def _execute_probe(
        self, name: str, adapter: ProviderAdapter, health: ProviderHealth
    ) -> None:
        """Execute a probe and update health metrics."""
        old_state = health.state
        start_time = time.monotonic()
        try:
            available = await asyncio.wait_for(
                adapter.health_check(),
                timeout=self.config.probe_timeout_seconds,
            )
            latency_ms = (time.monotonic() - start_time) * 1000
            health.last_check = time.time()
            health.latency_ms = latency_ms
            health.last_error = None
            if available:
                prev_failures = health.consecutive_failures
                health.success_count += 1
                health.last_success = time.time()
                health.consecutive_failures = 0
                health.state = (
                    ProviderState.DEGRADED
                    if latency_ms > self.config.latency_degraded_ms
                    else ProviderState.HEALTHY
                )
                if (
                    old_state in (ProviderState.DOWN, ProviderState.DEGRADED)
                    and health.state == ProviderState.HEALTHY
                    and prev_failures >= self.config.recovery_threshold - 1
                ):
                    self._emit_event(HealthEvent.PROVIDER_RECOVERED, name)
            else:
                health.error_count += 1
                health.consecutive_failures += 1
                health.last_error = "Health check returned false"
                self._update_state_on_failure(name, old_state)
        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            health.last_check = time.time()
            health.latency_ms = latency_ms
            health.error_count += 1
            health.consecutive_failures += 1
            health.last_error = f"Probe timed out after {self.config.probe_timeout_seconds}s"
            logger.warning("Health probe timed out for %s (%.0fms)", name, latency_ms)
            self._update_state_on_failure(name, old_state)
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            health.last_check = time.time()
            health.latency_ms = latency_ms
            health.error_count += 1
            health.consecutive_failures += 1
            health.last_error = str(e)[:200]
            self._update_state_on_failure(name, old_state)

    async def _probe_provider(self, name: str) -> None:
        """Probe a single provider with circuit breaker check."""
        health = self._providers.get(name)
        if not health or self._should_skip_probe(name):
            return

        # Lazy adapter resolution — retries each cycle for providers whose
        # adapters weren't resolvable at startup (e.g., credentials added later)
        adapter = self._adapters.get(name)
        if not adapter:
            try:
                from app.adapters.registry import get_adapter

                adapter = get_adapter(name)
                self._adapters[name] = adapter
            except Exception:
                return

        await self._execute_probe(name, adapter, health)

    async def _probe_loop(self) -> None:
        """Main probe loop that runs in background."""
        while self._running:
            probe_tasks = [self._probe_provider(name) for name in self._providers]
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
        """Check if a provider is available enough to attempt a real request."""
        health = self._providers.get(provider)
        if not health:
            return False
        return health.state in (
            ProviderState.HEALTHY,
            ProviderState.DEGRADED,
            ProviderState.UNKNOWN,
        )

    def get_available_providers(self) -> list[str]:
        """Get list of providers that are not currently known-down."""
        return [
            name
            for name, health in self._providers.items()
            if health.state in (
                ProviderState.HEALTHY,
                ProviderState.DEGRADED,
                ProviderState.UNKNOWN,
            )
        ]

    async def probe_now(self, provider: str | None = None) -> None:
        """Trigger immediate probe for one or all providers (bypasses circuit breaker)."""
        if provider:
            health = self._providers.get(provider)
            if not health:
                return
            # Lazy adapter resolution for manual probes too
            adapter = self._adapters.get(provider)
            if not adapter:
                try:
                    from app.adapters.registry import get_adapter

                    adapter = get_adapter(provider)
                    self._adapters[provider] = adapter
                except Exception:
                    return
            # Bypass circuit breaker for manual probes
            await self._execute_probe(provider, adapter, health)
        else:
            probe_tasks = [self._probe_provider(name) for name in self._providers]
            await asyncio.gather(*probe_tasks, return_exceptions=True)
