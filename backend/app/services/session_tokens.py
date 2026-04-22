"""Session token calculations and breakdowns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.api.schemas.sessions import AgentTokenBreakdown


def calculate_agent_token_breakdown(
    messages: list[Any],
) -> tuple[list[AgentTokenBreakdown], int, int]:
    """Calculate token breakdown by agent for multi-agent sessions.

    Args:
        messages: List of message objects

    Returns:
        Tuple of (agent_breakdown, total_input, total_output)
    """
    # Deferred import: importing app.api.schemas.sessions at module scope
    # triggers app.api.__init__ which pulls in sessions_router → session_helpers
    # → session_responses → session_tokens, causing a circular import when
    # service modules are imported directly (e.g., smoke tests).
    from app.api.schemas.sessions import AgentTokenBreakdown

    agent_stats: dict[str, dict[str, Any]] = {}
    total_input = 0
    total_output = 0

    # Group messages by agent_id
    for m in messages:
        agent_key = m.agent_id or "_default"
        if agent_key not in agent_stats:
            agent_stats[agent_key] = {
                "agent_id": m.agent_id or "default",
                "agent_name": m.agent_name,
                "input_tokens": 0,
                "output_tokens": 0,
                "message_count": 0,
            }
        tokens = m.tokens or 0
        if m.role == "user":
            agent_stats[agent_key]["input_tokens"] += tokens
            total_input += tokens
        else:
            agent_stats[agent_key]["output_tokens"] += tokens
            total_output += tokens
        agent_stats[agent_key]["message_count"] += 1

    # Build breakdown list (only if multiple agents or explicit agent_id)
    agent_breakdown: list[AgentTokenBreakdown] = []
    for stats in agent_stats.values():
        if stats["agent_id"] != "default" or len(agent_stats) > 1:
            agent_breakdown.append(
                AgentTokenBreakdown(
                    agent_id=stats["agent_id"],
                    agent_name=stats["agent_name"],
                    input_tokens=stats["input_tokens"],
                    output_tokens=stats["output_tokens"],
                    total_tokens=stats["input_tokens"] + stats["output_tokens"],
                    message_count=stats["message_count"],
                )
            )

    return agent_breakdown, total_input, total_output
