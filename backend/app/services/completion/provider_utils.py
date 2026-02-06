"""Provider detection and adapter management for completions."""

from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter] = {}


def get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get cached adapter instance."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    adapter: ClaudeAdapter | GeminiAdapter
    if provider == "claude":
        adapter = ClaudeAdapter()
    elif provider == "gemini":
        adapter = GeminiAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    _adapter_cache[provider] = adapter
    return adapter
