"""Provider-specific event stream construction for tool execution."""

from __future__ import annotations

from typing import Any

from app.adapters.base import Message

from .turn_budget import resolve_tool_max_turns


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
    return adapter.complete_with_tool_events(
        messages=messages,
        model=model,
        tools=tools or [],
        working_dir=working_dir,
        permission_config=permission_config,
        max_turns=effective_max_turns,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        tool_catalog=tool_catalog,
    )
