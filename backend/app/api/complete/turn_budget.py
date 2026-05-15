"""Shared turn-budget policy for completion orchestration."""

from __future__ import annotations

_OPENAI_COMPAT_TOOL_PROVIDERS = frozenset(
    {
        "cloudflare",
        "codex",
        "deepseek",
        "local",
        "minimax",
        "moonshot",
        "nvidia",
        "openai",
        "openrouter",
        "xai",
        "zhipu",
    }
)
_MIN_TOOL_COMPLETION_TURNS = 3


def uses_openai_compat_tool_loop(provider: str) -> bool:
    """Return True when provider tool execution uses the OpenAI-compat stream bridge."""
    return provider in _OPENAI_COMPAT_TOOL_PROVIDERS


def resolve_tool_max_turns(provider: str, requested_max_turns: int | None) -> int | None:
    """Return the effective tool-loop turn budget.

    Tool execution needs at least:
    1. one model turn to request tools
    2. one model turn after tool results
    3. one closeout turn if the model ends without a user-facing answer

    ``None`` means no local turn cap. Keep the floor small and provider-agnostic
    only when a caller explicitly provides a budget, so legacy low values do not
    break the tool-result closeout turn.
    """
    del provider  # Provider family no longer affects the minimum tool budget.
    if requested_max_turns is None:
        return None
    return max(requested_max_turns, _MIN_TOOL_COMPLETION_TURNS)
