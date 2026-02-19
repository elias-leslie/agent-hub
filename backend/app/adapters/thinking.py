"""Unified thinking/reasoning configuration across providers."""

from __future__ import annotations

from app.adapters.types import ThinkingLevel

# OpenAI reasoning_effort mapping
_OPENAI_REASONING_MAP: dict[str, str] = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "ultrathink": "high",
}


def _normalize_level(level: ThinkingLevel | str | None) -> str | None:
    """Normalize a thinking level to its string value, or None if off/absent."""
    if level is None:
        return None
    if isinstance(level, ThinkingLevel):
        if level is ThinkingLevel.OFF:
            return None
        return level.value
    # Raw string path
    level_lower = level.strip().lower()
    if level_lower == "off" or level_lower == "":
        return None
    return level_lower


def get_thinking_config(
    model: str,
    level: ThinkingLevel | str | None,
    provider: str,
) -> dict | None:
    """Get provider-specific thinking configuration.

    Args:
        model: The model identifier (e.g. "claude-sonnet-4-20250514").
        level: Desired thinking level as enum or string. None / "off" disables.
        provider: Provider name (e.g. "claude", "gemini", "openai", "openrouter").

    Returns:
        Dict of kwargs to pass to the provider, or None if thinking is
        not applicable or disabled.
    """
    level_str = _normalize_level(level)
    if level_str is None:
        return None

    provider_lower = provider.lower()

    if provider_lower == "claude":
        return {"thinking_level": level_str}

    if provider_lower == "gemini":
        return {"thinking_level": level_str}

    if provider_lower in ("openai", "openrouter", "xai", "zhipu"):
        effort = _OPENAI_REASONING_MAP.get(level_str, "medium")
        return {"reasoning_effort": effort}

    # Unknown provider — silently ignore
    return None
