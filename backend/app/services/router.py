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
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
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
    increment_circuit_trips,
)
from app.services.model_mapping import map_model_to_provider
from app.services.tier_classifier import Tier, get_model_for_tier
from app.services.tier_selection import select_model_by_tier

logger = logging.getLogger(__name__)

# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "gemini"]

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
        self._provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN
        self._adapter_factory = adapter_factory or {
            "claude": ClaudeAdapter,
            "gemini": GeminiAdapter,
        }
        self._adapters: dict[str, ProviderAdapter] = {}

        # Initialize circuit breaker and error tracking
        self._circuit_breaker = CircuitBreakerManager(self._provider_chain)
        self._error_tracker = ErrorTracker()

    def _get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        if provider not in self._adapters:
            factory = self._adapter_factory.get(provider)
            if not factory:
                raise ValueError(f"Unknown provider: {provider}")
            self._adapters[provider] = factory()
        return self._adapters[provider]

    def _determine_primary_provider(self, model: str) -> str:
        """Determine primary provider from model name."""
        model_lower = model.lower()
        if "claude" in model_lower:
            return "claude"
        elif "gemini" in model_lower:
            return "gemini"
        # Default to first in chain
        return self._provider_chain[0]

    def _get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        chain = [primary]
        for provider in self._provider_chain:
            if provider != primary and provider not in chain:
                chain.append(provider)
        return chain

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
        """Generate completion with automatic fallback and tier-based selection."""
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
                result = await self._try_provider(
                    provider, primary, model, messages, max_tokens, temperature, **kwargs
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
                last_error = await self._handle_provider_error(e, provider, model)
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

    async def _try_provider(
        self,
        provider: str,
        primary: str,
        model: str,
        messages: list[Message],
        max_tokens: int | None,
        temperature: float,
        **kwargs: Any,
    ) -> CompletionResult:
        """Try to get completion from a provider."""
        # Check circuit breaker
        if not await self._circuit_breaker.check_circuit(provider):
            state = self._circuit_breaker._get_circuit_state(provider)
            logger.warning(f"Circuit open for {provider}, skipping")
            raise CircuitBreakerError(
                provider=provider,
                consecutive_failures=state.consecutive_failures,
                last_error_signature=state.last_error_signature or "",
                cooldown_until=state.cooldown_until,
            )

        adapter = self._get_adapter(provider)

        # Map model for fallback providers
        effective_model = model
        if provider != primary:
            effective_model = map_model_to_provider(model, provider)
            logger.info(f"Fallback: {primary} -> {provider}, model: {model} -> {effective_model}")

        return await adapter.complete(
            messages=messages,
            model=effective_model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def _handle_provider_error(
        self, error: Exception, provider: str, model: str
    ) -> Exception:
        """Handle provider error and update circuit state."""
        if isinstance(error, RateLimitError):
            logger.warning(f"Rate limit on {provider}, trying next provider")
        elif isinstance(error, ProviderError) and error.retriable:
            logger.warning(f"Retriable error on {provider}: {error}, trying next provider")
        elif isinstance(error, ValueError):
            logger.warning(f"Config error for {provider}: {error}, trying next provider")
            return error  # Don't track config errors

        # Record error and update circuit breaker
        consecutive = self._error_tracker.record_error(error, provider, model)
        error_signature = self._error_tracker.compute_error_signature(error, provider, model)
        state = await self._circuit_breaker.on_failure(provider, consecutive, error_signature)

        # Trip circuit breaker if threshold reached
        if consecutive >= CIRCUIT_BREAKER_THRESHOLD:
            increment_circuit_trips()
            raise CircuitBreakerError(
                provider=provider,
                consecutive_failures=consecutive,
                last_error_signature=state.last_error_signature or "",
                cooldown_until=state.cooldown_until,
            )

        return error
