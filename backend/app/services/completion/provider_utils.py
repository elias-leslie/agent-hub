"""Provider detection and adapter management for completions."""

from app.adapters.base import ProviderAdapter

_adapter_cache: dict[str, ProviderAdapter] = {}


def _create_adapter(provider: str) -> ProviderAdapter:
    """Create adapter instance for the given provider."""
    if provider == "claude":
        from app.adapters.claude import ClaudeAdapter
        return ClaudeAdapter()
    elif provider == "gemini":
        from app.adapters.gemini import GeminiAdapter
        return GeminiAdapter()
    elif provider == "openrouter":
        from app.adapters.openrouter import OpenRouterAdapter
        return OpenRouterAdapter()
    elif provider == "openai":
        from app.adapters.openai import OpenAIAdapter
        return OpenAIAdapter()
    elif provider == "xai":
        from app.adapters.xai import XAIAdapter
        return XAIAdapter()
    elif provider == "zhipu":
        from app.adapters.zhipu import ZhipuAdapter
        return ZhipuAdapter()
    elif provider == "minimax":
        from app.adapters.minimax import MinimaxAdapter
        return MinimaxAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")


def get_adapter(provider: str) -> ProviderAdapter:
    """Get cached adapter instance."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    adapter = _create_adapter(provider)
    _adapter_cache[provider] = adapter
    return adapter
