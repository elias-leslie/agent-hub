"""Shared turn-budget policy for completion orchestration."""

from __future__ import annotations

_MIN_TOOL_COMPLETION_TURNS = 3


def resolve_tool_max_turns(requested_max_turns: int) -> int:
    """Return the effective tool-loop turn budget.

    Tool execution needs at least:
    1. one model turn to request tools
    2. one model turn after tool results
    3. one closeout turn if the model ends without a user-facing answer

    Keep the floor small and provider-agnostic so callers can set higher
    budgets deliberately.
    """
    return max(requested_max_turns, _MIN_TOOL_COMPLETION_TURNS)
