"""Provider chain management for model routing."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)

# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "cloudcode", "gemini", "minimax", "openrouter"]


def _default_adapter_factory() -> dict[str, Callable[[], ProviderAdapter]]:
    """Lazy-import adapters to break the circular import via app.services.__init__."""
    from app.adapters.claude import ClaudeAdapter
    from app.adapters.cloudcode_claude import CloudCodeClaudeAdapter
    from app.adapters.codex_oauth import CodexOAuthAdapter
    from app.adapters.gemini import GeminiAdapter
    from app.adapters.minimax import MinimaxAdapter
    from app.adapters.openai import OpenAIAdapter
    from app.adapters.openrouter import OpenRouterAdapter
    from app.adapters.xai import XAIAdapter
    from app.adapters.zhipu import ZhipuAdapter

    return {
        "claude": ClaudeAdapter,
        "cloudcode": CloudCodeClaudeAdapter,
        "codex": CodexOAuthAdapter,
        "gemini": GeminiAdapter,
        "openrouter": OpenRouterAdapter,
        "openai": OpenAIAdapter,
        "xai": XAIAdapter,
        "zhipu": ZhipuAdapter,
        "minimax": MinimaxAdapter,
    }


class ProviderChainManager:
    """Manages provider chain and adapter creation."""

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ) -> None:
        self.provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN
        self._adapter_factory = adapter_factory or _default_adapter_factory()
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
        # Prefix-based detection (order matters: openrouter/ before grok/gpt)
        if model_lower.startswith("openrouter/") or model_lower.startswith("or/"):
            return "openrouter"
        if model_lower.startswith("cloudcode/"):
            return "cloudcode"
        if model_lower.startswith("codex/"):
            return "codex"
        if model_lower.startswith("openai/"):
            return "openai"
        if model_lower.startswith("xai/"):
            return "xai"
        if model_lower.startswith("zhipu/"):
            return "zhipu"
        if model_lower.startswith("minimax/"):
            return "minimax"
        # Name-based detection
        if "claude" in model_lower:
            return "claude"
        if "gemini" in model_lower:
            return "gemini"
        if "gpt" in model_lower:
            return "openai"
        if "grok" in model_lower:
            return "xai"
        if "glm" in model_lower:
            return "zhipu"
        # Default to first in chain
        return self.provider_chain[0]

    def get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        chain = [primary]
        for provider in self.provider_chain:
            if provider != primary and provider not in chain:
                chain.append(provider)
        return chain
