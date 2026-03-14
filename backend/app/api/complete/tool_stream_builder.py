"""Provider-specific event stream construction for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.adapters.base import Message

from .turn_budget import resolve_tool_max_turns, uses_openai_compat_tool_loop

if TYPE_CHECKING:
    pass


def build_event_stream(
    adapter: Any,
    messages: list[Message],
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    max_turns: int,
    project_id: str | None,
    session_id: str,
    agent_slug: str | None,
) -> Any:
    """Select and return the appropriate async event stream for the provider."""
    effective_max_turns = resolve_tool_max_turns(provider, max_turns)

    if uses_openai_compat_tool_loop(provider):
        from .openai_event_adapter import adapt_openai_stream

        return adapt_openai_stream(
            adapter, messages, model, tools or [],
            working_dir, permission_config, effective_max_turns, project_id, session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
    if provider == "claude":
        from .claude_event_adapter import adapt_claude_stream

        raw_stream = adapter.complete_with_tools(
            messages=messages, model=model, tools=tools or [],
            working_dir=working_dir, permission_config=permission_config,
            project_id=project_id, max_turns=effective_max_turns,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
        return adapt_claude_stream(raw_stream)

    # Gemini and any other provider using ToolEvent natively
    kwargs: dict[str, Any] = {
        "messages": messages, "model": model, "tools": tools or [],
        "working_dir": working_dir, "permission_config": permission_config,
        "tool_catalog": tool_catalog,
    }
    if provider == "gemini":
        kwargs["max_turns"] = effective_max_turns
    if provider == "gemini" and project_id:
        kwargs["project_id"] = project_id
    if agent_slug:
        kwargs["agent_slug"] = agent_slug
    return adapter.complete_with_tools(**kwargs)
