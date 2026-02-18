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
from app.services.model_selector import ComplexityTier, QualityPreference, select_model
from app.services.provider_chain import ProviderChainManager
from app.services.request_executor import RequestExecutor
from app.services.tier_selection import select_model_by_tier

logger = logging.getLogger(__name__)

__all__ = [
    "CIRCUIT_BREAKER_COOLDOWN",
    "CIRCUIT_BREAKER_THRESHOLD",
    "THRASHING_THRESHOLD",
    "CircuitState",
    "ModelRouter",
    "get_router",
    "get_thrashing_metrics",
]

_router_instance: "ModelRouter | None" = None


def get_router() -> "ModelRouter":
    """Get or create the global ModelRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance


class ModelRouter:
    """Routes completion requests to providers with fallback and thrashing detection."""

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ):
        self._chain_manager = ProviderChainManager(provider_chain, adapter_factory)
        self._circuit_breaker = CircuitBreakerManager(self._chain_manager.provider_chain)
        self._error_tracker = ErrorTracker()
        self._executor = RequestExecutor(self._circuit_breaker, self._error_tracker)
        self._provider_chain = self._chain_manager.provider_chain
        self._adapter_factory = self._chain_manager._adapter_factory
        self._adapters = self._chain_manager._adapters

    def _determine_primary_provider(self, model: str) -> str:
        return self._chain_manager.determine_primary_provider(model)

    async def reset_circuit(self, provider: str) -> None:
        """Manually reset circuit breaker for a provider."""
        await self._circuit_breaker.reset_circuit(provider)

    def get_circuit_status(self) -> dict[str, dict[str, str | int | float | None]]:
        """Get current circuit breaker status for all providers."""
        return self._circuit_breaker.get_circuit_status()

    def _compute_error_signature(self, error: Exception, provider: str, model: str) -> str:
        return self._error_tracker.compute_error_signature(error, provider, model)

    def _record_error(self, error: Exception, provider: str, model: str) -> int:
        return self._error_tracker.record_error(error, provider, model)

    def _get_circuit_state(self, provider: str) -> CircuitBreakerState:
        return self._circuit_breaker._get_circuit_state(provider)

    def _resolve_model(
        self,
        model: str | None,
        messages: list[Message],
        auto_tier: bool,
        tier_preference: QualityPreference,
    ) -> str:
        """Resolve model from tier selection or default."""
        if auto_tier and not model:
            return select_model_by_tier(messages, self._provider_chain[0], tier_preference)
        if not model:
            entry = select_model(
                complexity=ComplexityTier.TIER_2,
                preference=tier_preference,
                provider=self._provider_chain[0],
            )
            return entry.id
        return model

    async def _escalate_and_retry(
        self,
        current_preference: QualityPreference,
        provider: str,
        primary: str,
        messages: list[Message],
        max_tokens: int | None,
        temperature: float,
        auto_tier: bool,
        **kwargs: Any,
    ) -> tuple[QualityPreference, CompletionResult | None]:
        """Attempt tier escalation on the same provider; returns (pref, result|None)."""
        from app.services.model_selector import escalate_preference

        escalated = escalate_preference(current_preference)
        if not (escalated and auto_tier):
            return current_preference, None
        logger.info(f"Escalating tier from {current_preference} to {escalated}")
        try:
            new_model = select_model_by_tier(messages, provider, escalated)
            logger.info(f"Retrying with escalated model: {new_model}")
            adapter = self._chain_manager.get_adapter(provider)
            result = await self._executor.try_provider(
                adapter, provider, primary, new_model, messages, max_tokens, temperature, **kwargs
            )
            await self._circuit_breaker.on_success(provider)
            logger.info(f"Request succeeded after tier escalation to {escalated}")
            return escalated, result
        except Exception as err:
            logger.warning(f"Tier escalation attempt failed: {err}")
            return escalated, None

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        auto_tier: bool = False,
        tier_preference: QualityPreference = QualityPreference.STANDARD,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate a completion, falling back across providers on failure."""
        model = self._resolve_model(model, messages, auto_tier, tier_preference)
        primary = self._determine_primary_provider(model)
        chain = self._chain_manager.get_fallback_chain(primary)
        last_error: Exception | None = None
        current_preference = tier_preference

        for i, provider in enumerate(chain):
            try:
                adapter = self._chain_manager.get_adapter(provider)
                result = await self._executor.try_provider(
                    adapter, provider, primary, model, messages, max_tokens, temperature, **kwargs
                )
                await self._circuit_breaker.on_success(provider)
                (logger.info if i > 0 else logger.debug)(
                    f"Request served by {'fallback' if i > 0 else 'primary'} provider: {provider}"
                )
                return result

            except CircuitBreakerError as e:
                last_error = e

            except (RateLimitError, ProviderError, ValueError) as e:
                last_error = await self._executor.handle_provider_error(e, provider, model)
                if isinstance(e, ProviderError) and not e.retriable:
                    raise
                current_preference, escalated_result = await self._escalate_and_retry(
                    current_preference, provider, primary, messages, max_tokens, temperature,
                    auto_tier, **kwargs
                )
                if escalated_result is not None:
                    return escalated_result

        logger.error(f"All providers failed. Last error: {last_error}")
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(
            f"All providers failed: {last_error}", provider="router", retriable=False
        )
