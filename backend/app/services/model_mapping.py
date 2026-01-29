"""Model mapping utilities for provider fallback."""

from app.constants import (
    CLAUDE_SONNET,
    CLAUDE_TO_GEMINI_MAP,
    GEMINI_FLASH,
    GEMINI_TO_CLAUDE_MAP,
)


def map_model_to_provider(original_model: str, target_provider: str) -> str:
    """Map a model from one provider to an equivalent in another.

    This is a simple mapping for fallback scenarios.

    Args:
        original_model: Original model identifier
        target_provider: Target provider name (claude or gemini)

    Returns:
        Mapped model identifier for target provider
    """
    if target_provider == "gemini":
        return CLAUDE_TO_GEMINI_MAP.get(original_model, GEMINI_FLASH)
    elif target_provider == "claude":
        return GEMINI_TO_CLAUDE_MAP.get(original_model, CLAUDE_SONNET)
    else:
        return original_model
