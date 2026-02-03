"""Provider detection and adapter management for completions."""

from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

# Adapter cache
_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter] = {}


def get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    return "claude"


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
