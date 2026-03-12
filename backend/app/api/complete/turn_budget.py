"""Shared turn-budget policy for completion orchestration."""

from __future__ import annotations

_OPENAI_COMPAT_TOOL_PROVIDERS = frozenset(
    {"openai", "openrouter", "xai", "zhipu", "minimax", "nvidia", "codex"}
)
_OPENAI_COMPAT_TOOL_MIN_TURNS = 20
_NATIVE_TOOL_MIN_TURNS = 5


def uses_openai_compat_tool_loop(provider: str) -> bool:
    """Return True when provider tool execution uses the OpenAI-compat stream bridge."""
    return provider in _OPENAI_COMPAT_TOOL_PROVIDERS


def resolve_tool_max_turns(provider: str, requested_max_turns: int) -> int:
    """Return the effective tool-loop turn budget for a provider."""
    if provider == "claude":
        return requested_max_turns
    if uses_openai_compat_tool_loop(provider):
        return max(requested_max_turns, _OPENAI_COMPAT_TOOL_MIN_TURNS)
    return max(requested_max_turns, _NATIVE_TOOL_MIN_TURNS)
