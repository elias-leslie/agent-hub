"""Provider-specific event stream construction for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.adapters.base import Message

if TYPE_CHECKING:
    pass

# Providers whose complete_with_tools uses OpenAI-compat pattern
_OPENAI_COMPAT_PROVIDERS = frozenset({"openai", "openrouter", "xai", "zhipu", "minimax", "nvidia", "codex"})


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
    if provider in _OPENAI_COMPAT_PROVIDERS:
        from .openai_event_adapter import adapt_openai_stream

        return adapt_openai_stream(
            adapter, messages, model, tools or [],
            working_dir, permission_config, max_turns, project_id, session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
    if provider == "claude":
        from .claude_event_adapter import adapt_claude_stream

        raw_stream = adapter.complete_with_tools(
            messages=messages, model=model, tools=tools or [],
            working_dir=working_dir, permission_config=permission_config,
            project_id=project_id, max_turns=max_turns,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
        return adapt_claude_stream(raw_stream)

    # Gemini, CloudCode, and any other provider using ToolEvent natively
    kwargs: dict[str, Any] = {
        "messages": messages, "model": model, "tools": tools or [],
        "working_dir": working_dir, "permission_config": permission_config,
        "tool_catalog": tool_catalog,
    }
    if provider in ("gemini", "cloudcode"):
        kwargs["max_turns"] = max_turns
    if provider in ("gemini", "cloudcode") and project_id:
        kwargs["project_id"] = project_id
    if agent_slug:
        kwargs["agent_slug"] = agent_slug
    return adapter.complete_with_tools(**kwargs)
