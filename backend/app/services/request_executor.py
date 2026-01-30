"""Request execution logic for model routing."""

import logging
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
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreakerManager,
)
from app.services.error_tracking import ErrorTracker, increment_circuit_trips
from app.services.model_mapping import map_model_to_provider

logger = logging.getLogger(__name__)


class RequestExecutor:
    """Executes requests with error handling and circuit breaker integration."""

    def __init__(
        self,
        circuit_breaker: CircuitBreakerManager,
        error_tracker: ErrorTracker,
    ):
        """Initialize request executor.

        Args:
            circuit_breaker: Circuit breaker manager
            error_tracker: Error tracker
        """
        self._circuit_breaker = circuit_breaker
        self._error_tracker = error_tracker

    async def try_provider(
        self,
        adapter: ProviderAdapter,
        provider: str,
        primary: str,
        model: str,
        messages: list[Message],
        max_tokens: int | None,
        temperature: float,
        **kwargs: Any,
    ) -> CompletionResult:
        """Try to get completion from a provider.

        Args:
            adapter: Provider adapter
            provider: Provider name
            primary: Primary provider name
            model: Model identifier
            messages: Conversation messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters

        Returns:
            Completion result

        Raises:
            CircuitBreakerError: If circuit is open
        """
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

    async def handle_provider_error(self, error: Exception, provider: str, model: str) -> Exception:
        """Handle provider error and update circuit state.

        Args:
            error: The error that occurred
            provider: Provider name
            model: Model identifier

        Returns:
            The error (potentially modified)

        Raises:
            CircuitBreakerError: If circuit threshold is reached
        """
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
