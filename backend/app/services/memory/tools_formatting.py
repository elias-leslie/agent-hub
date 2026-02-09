"""Formatting utilities for memory tools.

Helper functions for formatting session context for injection.
"""

from .tools_schemas import SessionContextResponse


def format_session_context_for_injection(context: SessionContextResponse) -> str:
    """
    Format session context as a string for system prompt injection.

    Args:
        context: SessionContextResponse with categorized learnings

    Returns:
        Formatted string suitable for injection into prompts
    """
    if context.session_count == 0:
        return ""

    parts = []

    if context.patterns:
        parts.append("## Relevant Patterns")
        for p in context.patterns:
            parts.append(f"- {p.content}")

    if context.gotchas:
        parts.append("\n## Known Gotchas")
        for g in context.gotchas:
            parts.append(f"- {g.content}")

    if context.discoveries:
        parts.append("\n## Recent Discoveries")
        for d in context.discoveries[:5]:  # Limit discoveries
            parts.append(f"- {d.content}")

    return "\n".join(parts)
