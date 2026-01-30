"""Provider chain management for model routing."""

import logging
from collections.abc import Callable

from app.adapters.base import ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

logger = logging.getLogger(__name__)

# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "gemini"]


class ProviderChainManager:
    """Manages provider chain and adapter creation."""

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ):
        """Initialize provider chain manager.

        Args:
            provider_chain: Order of providers to try. Defaults to ["claude", "gemini"].
            adapter_factory: Factory functions to create adapters. Defaults to built-in adapters.
        """
        self.provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN
        self._adapter_factory = adapter_factory or {
            "claude": ClaudeAdapter,
            "gemini": GeminiAdapter,
        }
        self._adapters: dict[str, ProviderAdapter] = {}

    def get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        if provider not in self._adapters:
            factory = self._adapter_factory.get(provider)
            if not factory:
                raise ValueError(f"Unknown provider: {provider}")
            self._adapters[provider] = factory()
        return self._adapters[provider]

    def determine_primary_provider(self, model: str) -> str:
        """Determine primary provider from model name."""
        model_lower = model.lower()
        if "claude" in model_lower:
            return "claude"
        elif "gemini" in model_lower:
            return "gemini"
        # Default to first in chain
        return self.provider_chain[0]

    def get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        chain = [primary]
        for provider in self.provider_chain:
            if provider != primary and provider not in chain:
                chain.append(provider)
        return chain
