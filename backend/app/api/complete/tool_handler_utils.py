"""Shared utilities and helper functions for tool execution handlers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession

from .tool_event_processor import process_tool_event
from .tool_models import ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["_ExecutionState", "_init_execution_state", "_run_tool_loop"]

# Providers whose complete_with_tools uses OpenAI-compat pattern
_OPENAI_COMPAT_PROVIDERS = frozenset({"openai", "openrouter", "xai", "zhipu", "minimax"})

# Feature flag for gradual rollout (Phase 1)
USE_UNIFIED_TOOL_PROCESSOR = os.environ.get("USE_UNIFIED_TOOL_PROCESSOR", "1") == "1"


@dataclass
class _ExecutionState:
    """Shared mutable state for a tool execution run."""

    agent_slug: str | None
    messages_for_adapter: list[Message]
    content_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    tool_calls_count: int = 0
    turn: int = 0


def _init_execution_state(
    session: DBSession,
    messages: list[dict[str, Any]],
) -> _ExecutionState:
    """Build shared execution state from session and raw messages."""
    agent_slug = getattr(session, "agent_slug", None)
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    return _ExecutionState(agent_slug=agent_slug, messages_for_adapter=messages_for_adapter)


async def _run_tool_loop(
    adapter: Any,
    state: _ExecutionState,
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    session_id: str,
    loaded_memory_uuids: list[str],
    db: AsyncSession,
    tracker: ProgressTracker,
    max_turns: int = 1,
    project_id: str | None = None,
) -> ToolExecutionResult | None:
    """Unified tool loop for all providers.

    Streams events from the adapter's complete_with_tools(), converting
    provider-specific events to ToolEvent format, then processing each
    through the unified tool_event_processor.

    Returns an error result on failure, else None (results in state).
    """
    if provider in _OPENAI_COMPAT_PROVIDERS:
        from .openai_event_adapter import adapt_openai_stream

        event_stream = adapt_openai_stream(
            adapter, state.messages_for_adapter, model, tools or [],
            working_dir, permission_config, max_turns, project_id,
        )
    elif provider == "claude":
        from .claude_event_adapter import adapt_claude_stream

        raw_stream = adapter.complete_with_tools(
            messages=state.messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            permission_config=permission_config,
        )
        event_stream = adapt_claude_stream(raw_stream)
    else:
        # Gemini, CloudCode, and any other provider using ToolEvent natively
        kwargs: dict[str, Any] = {
            "messages": state.messages_for_adapter,
            "model": model,
            "tools": tools or [],
            "working_dir": working_dir,
            "permission_config": permission_config,
        }
        if provider in ("gemini", "cloudcode"):
            kwargs["max_turns"] = max_turns
        if provider in ("gemini", "cloudcode") and project_id:
            kwargs["project_id"] = project_id
        event_stream = adapter.complete_with_tools(**kwargs)

    async for event, _session_id in event_stream:
        state.turn, tools_delta, error_message = await process_tool_event(
            event, state.turn, session_id, db, state.content_parts,
            state.thinking_parts, tracker, model_used=model, agent_id=state.agent_slug,
        )
        state.tool_calls_count += tools_delta

        if error_message:
            return build_error_result(
                Exception(error_message), model, provider, session_id, loaded_memory_uuids,
            )

    return None
