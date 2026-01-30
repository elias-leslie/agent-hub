"""Model router with fallback and tier-based selection support."""

import logging
from collections.abc import Callable
from typing import Any

from app.adapters.base import (
    CircuitBreakerError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
)
from app.services.circuit_breaker import (
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreakerManager,
    CircuitBreakerState,
    CircuitState,
)
from app.services.error_tracking import (
    THRASHING_THRESHOLD,
    ErrorTracker,
    get_thrashing_metrics,
)
from app.services.provider_chain import ProviderChainManager
from app.services.request_executor import RequestExecutor
from app.services.tier_classifier import Tier, get_model_for_tier
from app.services.tier_selection import select_model_by_tier

logger = logging.getLogger(__name__)

# Re-export constants for backwards compatibility
__all__ = [
    "CIRCUIT_BREAKER_COOLDOWN",
    "CIRCUIT_BREAKER_THRESHOLD",
    "THRASHING_THRESHOLD",
    "CircuitState",
    "ModelRouter",
    "get_router",
    "get_thrashing_metrics",
]

# Global router instance
_router_instance: "ModelRouter | None" = None


def get_router() -> "ModelRouter":
    """Get or create the global ModelRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance


class ModelRouter:
    """Routes completion requests to providers with fallback support.

    When the primary provider fails (rate limit, error), automatically
    tries the next provider in the chain. Includes thrashing detection
    to avoid repeated identical failures.
    """

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ):
        """Initialize router with provider chain.

        Args:
            provider_chain: Order of providers to try. Defaults to ["claude", "gemini"].
            adapter_factory: Factory functions to create adapters. Defaults to built-in adapters.
        """
        # Initialize components
        self._chain_manager = ProviderChainManager(provider_chain, adapter_factory)
        self._circuit_breaker = CircuitBreakerManager(self._chain_manager.provider_chain)
        self._error_tracker = ErrorTracker()
        self._executor = RequestExecutor(self._circuit_breaker, self._error_tracker)

        # Keep backwards compatible properties
        self._provider_chain = self._chain_manager.provider_chain
        self._adapter_factory = self._chain_manager._adapter_factory
        self._adapters = self._chain_manager._adapters

    def _get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        return self._chain_manager.get_adapter(provider)

    def _determine_primary_provider(self, model: str) -> str:
        """Determine primary provider from model name."""
        return self._chain_manager.determine_primary_provider(model)

    def _get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        return self._chain_manager.get_fallback_chain(primary)

    def reset_circuit(self, provider: str) -> None:
        """Manually reset circuit breaker for a provider."""
        self._circuit_breaker.reset_circuit(provider)

    def get_circuit_status(self) -> dict[str, dict[str, str | int | float | None]]:
        """Get current circuit breaker status for all providers."""
        return self._circuit_breaker.get_circuit_status()

    # Expose internal methods for testing
    def _compute_error_signature(self, error: Exception, provider: str, model: str) -> str:
        """Compute a signature for an error to detect identical failures."""
        return self._error_tracker.compute_error_signature(error, provider, model)

    def _record_error(self, error: Exception, provider: str, model: str) -> int:
        """Record an error and return consecutive identical error count."""
        return self._error_tracker.record_error(error, provider, model)

    def _get_circuit_state(self, provider: str) -> CircuitBreakerState:
        """Get circuit state for provider (for testing)."""
        return self._circuit_breaker._get_circuit_state(provider)

    def _check_thrashing(self, current_sig: str, history_count: int) -> int:
        """Check for thrashing (for testing)."""
        return self._error_tracker._check_thrashing(current_sig, history_count)

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        auto_tier: bool = False,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion with automatic fallback and tier-based selection.

        Args:
            messages: Conversation messages
            model: Model identifier (optional if auto_tier=True)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            auto_tier: Automatically select model based on message complexity
            **kwargs: Additional provider-specific parameters

        Returns:
            Completion result

        Raises:
            ProviderError: If all providers fail
        """
        # Auto-select model based on tier if requested
        if auto_tier and not model:
            model = select_model_by_tier(messages, self._provider_chain[0])

        # Default model if still not set
        if not model:
            model = get_model_for_tier(Tier.TIER_2, self._provider_chain[0])

        primary = self._determine_primary_provider(model)
        chain = self._get_fallback_chain(primary)

        last_error: Exception | None = None

        for i, provider in enumerate(chain):
            try:
                adapter = self._get_adapter(provider)
                result = await self._executor.try_provider(
                    adapter, provider, primary, model, messages, max_tokens, temperature, **kwargs
                )

                # Success - reset circuit state
                await self._circuit_breaker.on_success(provider)

                if i > 0:
                    logger.info(f"Request served by fallback provider: {provider}")
                else:
                    logger.debug(f"Request served by primary provider: {provider}")

                return result

            except CircuitBreakerError as e:
                # Store and continue to next provider
                last_error = e
                continue

            except (RateLimitError, ProviderError, ValueError) as e:
                last_error = await self._executor.handle_provider_error(e, provider, model)
                if isinstance(e, ProviderError) and not e.retriable:
                    # Non-retriable error - don't try other providers
                    raise
                continue

        # All providers failed
        logger.error(f"All providers failed. Last error: {last_error}")
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(
            f"All providers failed: {last_error}",
            provider="router",
            retriable=False,
        )
