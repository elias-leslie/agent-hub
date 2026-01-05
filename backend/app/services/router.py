"""Model router with fallback and tier-based selection support."""

import logging
from typing import Callable

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.services.tier_classifier import Tier, classify_request, get_model_for_tier

logger = logging.getLogger(__name__)


# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "gemini"]


class ModelRouter:
    """
    Routes completion requests to providers with fallback support.

    When the primary provider fails (rate limit, error), automatically
    tries the next provider in the chain.
    """

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ):
        """
        Initialize router with provider chain.

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

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        auto_tier: bool = False,
        **kwargs,
    ) -> CompletionResult:
        """
        Generate completion with automatic fallback and optional tier-based selection.

        Tries primary provider first, falls back to others on failure.
        Logs which provider actually served the request.

        Args:
            messages: Conversation messages
            model: Model identifier. If None and auto_tier=True, selects based on complexity.
            max_tokens: Maximum response tokens
            temperature: Sampling temperature
            auto_tier: If True and model not specified, auto-select model based on complexity
            **kwargs: Additional provider-specific parameters

        Returns:
            CompletionResult from the provider that succeeded

        Raises:
            ProviderError: If all providers fail
        """
        # Auto-select model based on tier if requested
        tier: Tier | None = None
        if auto_tier and not model:
            # Extract prompt from last user message for classification
            prompt = ""
            for msg in reversed(messages):
                if msg.role == "user":
                    prompt = msg.content
                    break
            tier = classify_request(prompt)
            model = get_model_for_tier(tier, self._provider_chain[0])
            logger.info(f"Auto-tier selected: tier={tier}, model={model}")

        # Default model if still not set
        if not model:
            model = get_model_for_tier(Tier.TIER_2, self._provider_chain[0])

        primary = self._determine_primary_provider(model)
        chain = self._get_fallback_chain(primary)

        last_error: Exception | None = None

        for i, provider in enumerate(chain):
            try:
                adapter = self._get_adapter(provider)

                # For fallback providers, we may need to map the model
                effective_model = model
                if provider != primary:
                    effective_model = self._map_model_to_provider(model, provider)
                    logger.info(
                        f"Fallback: {primary} -> {provider}, model: {model} -> {effective_model}"
                    )

                result = await adapter.complete(
                    messages=messages,
                    model=effective_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )

                if i > 0:
                    logger.info(f"Request served by fallback provider: {provider}")
                else:
                    logger.debug(f"Request served by primary provider: {provider}")

                return result

            except RateLimitError as e:
                logger.warning(f"Rate limit on {provider}, trying next provider")
                last_error = e
                continue

            except ProviderError as e:
                if e.retriable:
                    logger.warning(f"Retriable error on {provider}: {e}, trying next provider")
                    last_error = e
                    continue
                else:
                    # Non-retriable error (e.g., auth) - don't try other providers
                    raise

            except ValueError as e:
                # Configuration error (e.g., missing API key) - try next provider
                logger.warning(f"Config error for {provider}: {e}, trying next provider")
                last_error = e
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

    def _map_model_to_provider(self, original_model: str, target_provider: str) -> str:
        """
        Map a model from one provider to an equivalent in another.

        This is a simple mapping for fallback scenarios.
        """
        # Claude -> Gemini mapping (by capability tier)
        claude_to_gemini = {
            "claude-haiku-4-5-20250514": "gemini-2.0-flash",
            "claude-sonnet-4-5-20250514": "gemini-2.5-flash-preview-05-20",
            "claude-opus-4-5-20250514": "gemini-2.5-pro-preview-06-05",
        }

        # Gemini -> Claude mapping
        gemini_to_claude = {
            "gemini-2.0-flash": "claude-haiku-4-5-20250514",
            "gemini-2.5-flash-preview-05-20": "claude-sonnet-4-5-20250514",
            "gemini-2.5-pro-preview-06-05": "claude-opus-4-5-20250514",
        }

        if target_provider == "gemini":
            return claude_to_gemini.get(original_model, "gemini-2.0-flash")
        elif target_provider == "claude":
            return gemini_to_claude.get(original_model, "claude-sonnet-4-5-20250514")
        else:
            return original_model
