"""Shared turn-budget policy for completion orchestration."""

from __future__ import annotations

from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS

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


def tool_loop_turns(execute_tools: bool, requested_max_turns: int) -> int:
    """Turn cap to hand the tool loop: the shared agentic headroom unless the caller asked for more than one turn.

    A tool-executing call that leaves ``max_turns`` at its single-turn default would otherwise be cut off after
    one model turn; ``CompletionRequest`` applies the same rule to HTTP callers.
    """
    if execute_tools and requested_max_turns <= 1:
        return DEFAULT_AGENTIC_MAX_TURNS
    return requested_max_turns
