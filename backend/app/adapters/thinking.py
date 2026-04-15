"""Unified thinking/reasoning configuration across providers."""

from __future__ import annotations

from app.adapters.types import ThinkingLevel
from app.constants.catalog import get_model_capabilities

# OpenAI reasoning_effort mapping
_OPENAI_REASONING_MAP: dict[str, str] = {
    "none": "none",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
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
    if level_lower in {"off", "none", ""}:
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
    capabilities = get_model_capabilities(model)
    if capabilities is not None and not capabilities.has_thinking:
        return None

    if level_str == "xhigh" and capabilities is not None and not capabilities.supports_xhigh:
        level_str = "high"

    if provider_lower == "claude":
        return {"thinking_level": level_str}

    if provider_lower == "gemini":
        return {"thinking_level": level_str}

    if provider_lower == "xai":
        return None

    if provider_lower in ("openai", "openrouter", "zhipu", "codex", "minimax"):
        effort = _OPENAI_REASONING_MAP.get(level_str, "medium")
        return {"reasoning_effort": effort}

    # Unknown provider — silently ignore
    return None
