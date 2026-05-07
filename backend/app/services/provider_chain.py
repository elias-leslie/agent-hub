"""Provider chain management for model routing."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.adapters.base import ProviderAdapter
from app.adapters.registry import get_adapter as registry_get_adapter
from app.adapters.registry import get_provider_for_model

logger = logging.getLogger(__name__)

# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "gemini", "minimax", "kimi-code", "nvidia", "openrouter"]


class ProviderChainManager:
    """Manages provider chain and adapter creation."""

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ) -> None:
        self.provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN
        self._adapter_factory = adapter_factory
        self._adapters: dict[str, ProviderAdapter] = {}

    def get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        if provider not in self._adapters:
            if self._adapter_factory:
                # Custom factory (e.g., testing) — use it directly
                factory = self._adapter_factory.get(provider)
                if not factory:
                    raise ValueError(f"Unknown provider: {provider}")
                self._adapters[provider] = factory()
            else:
                # Default: delegate to unified registry
                self._adapters[provider] = registry_get_adapter(provider)
        return self._adapters[provider]

    def determine_primary_provider(self, model: str) -> str:
        """Determine primary provider from model name."""
        return get_provider_for_model(model)

    def get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        chain = [primary]
        for provider in self.provider_chain:
            if provider != primary and provider not in chain:
                chain.append(provider)
        return chain
