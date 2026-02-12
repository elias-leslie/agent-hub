"""Model mapping utilities for provider fallback."""

from __future__ import annotations

from app.constants import (
    CLAUDE_SONNET,
    CLAUDE_TO_GEMINI_MAP,
    GEMINI_FLASH,
    GEMINI_TO_CLAUDE_MAP,
    OPENAI_TO_CLAUDE_MAP,
    XAI_TO_CLAUDE_MAP,
    ZHIPU_TO_CLAUDE_MAP,
)


def map_model_to_provider(original_model: str, target_provider: str) -> str:
    """Map a model from one provider to an equivalent in another.

    This is a simple mapping for fallback scenarios.

    Args:
        original_model: Original model identifier
        target_provider: Target provider name

    Returns:
        Mapped model identifier for target provider
    """
    if target_provider == "gemini":
        return CLAUDE_TO_GEMINI_MAP.get(original_model, GEMINI_FLASH)
    elif target_provider == "claude":
        # Try all provider maps that fall back to Claude
        for mapping in (GEMINI_TO_CLAUDE_MAP, OPENAI_TO_CLAUDE_MAP, XAI_TO_CLAUDE_MAP, ZHIPU_TO_CLAUDE_MAP):
            if original_model in mapping:
                return mapping[original_model]
        return CLAUDE_SONNET
    else:
        return original_model
