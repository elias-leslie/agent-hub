"""Gemini thinking level configuration."""

from google.genai import types

# Gemini 3 thinking level mappings
# Gemini 3 Pro: supports "low", "high"
# Gemini 3 Flash: supports "minimal", "low", "medium", "high"
# Reference: https://ai.google.dev/gemini-api/docs/gemini-3
GEMINI_3_PRO_THINKING_LEVELS = {"low", "high"}
GEMINI_3_FLASH_THINKING_LEVELS = {"minimal", "low", "medium", "high"}

# Map unified API thinking levels to Gemini-specific levels
# Unified levels: minimal, low, medium, high, ultrathink
THINKING_LEVEL_MAP_PRO = {
    "minimal": "low",  # Pro doesn't support minimal, use low
    "low": "low",
    "medium": "high",  # Pro doesn't support medium, use high
    "high": "high",
    "ultrathink": "high",  # Pro max is high
}

THINKING_LEVEL_MAP_FLASH = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "ultrathink": "high",  # Flash max is high
}


def get_thinking_level(model: str, thinking_level: str | None) -> types.ThinkingLevel | None:
    """Convert thinking_level to Gemini-compatible value.

    Args:
        model: Model name (e.g., "gemini-3.1-pro-preview")
        thinking_level: User-specified thinking level (minimal/low/medium/high/ultrathink)

    Returns:
        Gemini-compatible ThinkingLevel enum value, or None if not requested
    """
    # Only enable thinking if explicitly requested
    # Thinking tokens count against max_tokens, so don't enable by default
    if not thinking_level:
        return None

    # Only Gemini 3 models support thinking config
    is_gemini_3 = "gemini-3" in model
    if not is_gemini_3:
        return None

    is_pro = "pro" in model.lower()
    level_map = THINKING_LEVEL_MAP_PRO if is_pro else THINKING_LEVEL_MAP_FLASH

    level_str = level_map.get(thinking_level, "high")
    # Convert string to ThinkingLevel enum
    return getattr(types.ThinkingLevel, level_str.upper(), types.ThinkingLevel.HIGH)
