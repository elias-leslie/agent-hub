"""New pi-mono-shaped completion pipeline (Phase 3.5 wiring).

Composes the post-collapse modules — ``session_repo``, ``app.routing``,
``app.memory``, ``app.llm.stream``, ``app.llm.tool_loop`` — into a single
entry point that mirrors the legacy ``complete_internal`` surface so the
HTTP route handler can branch on ``settings.llm_use_new_pipeline``
without touching the rest of the request shape.

Phase 3.6 wires server-side tool execution by adapting
``app.services.tools.create_direct_handler`` into the pi-mono ``ToolRunner``
callback the unified tool loop consumes. Phase 4 deletes the legacy
branch and this module's ``CompletionInternalResult`` adapter shim.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.session_repo import setup_completion_session
from app.api.complete.types import CompletionInternalResult
from app.llm.model_resolver import resolve_llm_model
from app.llm.tool_loop import ToolRunner
from app.llm.types import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from app.memory.citation_extractor import extract_cited_uuids
from app.memory.injection import inject_memory_context
from app.services.tools.base import ToolCall as ServiceToolCall
from app.services.tools.base import ToolCaller
from app.services.tools.tool_handler import create_direct_handler

from .orchestrator import build_context_from_messages, run_completion


def _assistant_text(message: AssistantMessage) -> str:
    """Flatten the final AssistantMessage content to a single string."""
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "".join(parts)


def _assistant_thinking(message: AssistantMessage) -> tuple[str | None, int | None]:
    """Extract concatenated thinking text + token estimate from the final message."""
    chunks: list[str] = []
    for block in message.content:
        if isinstance(block, ThinkingContent) and block.thinking:
            chunks.append(block.thinking)
    if not chunks:
        return None, None
    thinking = "\n".join(chunks)
    return thinking, len(thinking) // 4  # rough token estimate


def _assistant_tool_calls(message: AssistantMessage) -> list[ToolCall]:
    return [block for block in message.content if isinstance(block, ToolCall)]


def _make_tool_runner(
    *,
    working_dir: str | None,
    project_id: str | None,
    session_id: str | None,
    agent_slug: str | None,
) -> ToolRunner:
    """Bridge ``app.services.tools`` into a pi-mono ``ToolRunner`` callback.

    The unified tool loop consumes :class:`app.llm.types.ToolCall` and emits
    :class:`app.llm.types.ToolResultMessage`. The agent-hub tool runtime
    uses its own ``ToolCall`` / ``ToolResult`` shape, so we adapt at this
    boundary — the adapter layer itself never imports either side of the
    bridge.
    """

    handler = create_direct_handler(
        working_dir=working_dir,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
    )

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        service_call = ServiceToolCall(
            id=call.id,
            name=call.name,
            input=dict(call.arguments or {}),
            caller=ToolCaller(type="direct"),
        )
        result = await handler.execute(service_call)
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=[TextContent(text=result.content)],
            is_error=bool(result.is_error),
            timestamp=int(time.time() * 1000),
        )

    return run_tool


async def complete_internal_new_pipeline(
    *,
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    project_id: str,
    db: AsyncSession,
    session_id: str | None = None,
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    parent_session_id: str | None = None,
    agent_slug: str | None = None,
    use_memory: bool = False,
    memory_group_id: str | None = None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    working_dir: str | None = None,
    trace_id: str | None = None,
    requested_model: str | None = None,
    requested_provider: str | None = None,
    execute_tools: bool = False,
    max_turns: int = 1,
    **_unused: Any,
) -> CompletionInternalResult:
    """Run a completion via the new ``app.llm`` pipeline.

    Shape mirrors ``app.api.complete.core.complete_internal`` so the HTTP
    route can branch on ``settings.llm_use_new_pipeline`` without
    reshaping its inputs. ``execute_tools=True`` runs the unified tool
    loop with ``app.services.tools`` as the runner (Phase 3.6); fallback
    routing is deferred to Phase 4 once the legacy path is gone.
    """

    _session, session_id, _is_new, messages_dict = await setup_completion_session(
        db, session_id, project_id, provider, model,
        external_id, client_id, request_source, agent_slug, current_branch, working_dir,
        parent_session_id, messages, trace_id=trace_id,
        requested_provider=requested_provider or provider,
        requested_model=requested_model or model,
    )

    loaded_memory_uuids: list[str] = []
    if use_memory:
        messages_dict, loaded_memory_uuids, _ = await inject_memory_context(
            messages_dict, db, session_id, memory_group_id, task_type, phase,
            memory_config, current_branch=current_branch, agent_id=agent_slug,
        )

    llm_model = resolve_llm_model(model, provider)
    context = build_context_from_messages(messages_dict)

    run_tool = (
        _make_tool_runner(
            working_dir=working_dir,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_slug,
        )
        if execute_tools
        else None
    )

    started = time.monotonic()
    result = await run_completion(
        llm_model,
        context,
        execute_tools=execute_tools,
        run_tool=run_tool,
        max_turns=max_turns,
    )
    _elapsed_ms = int((time.monotonic() - started) * 1000)
    message = result.message

    content = _assistant_text(message)
    thinking_content, thinking_tokens = _assistant_thinking(message)
    cited_uuids = await extract_cited_uuids(content, memory_group_id) if use_memory else []

    return CompletionInternalResult(
        content=content,
        model=model,
        provider=provider,
        input_tokens=message.usage.input,
        output_tokens=message.usage.output,
        finish_reason=message.stop_reason,
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        tool_calls=[
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in _assistant_tool_calls(message)
        ] or None,
        turns=result.turns,
        tool_calls_count=result.tool_calls_count,
        model_used=model,
        requested_model=requested_model or model,
        requested_provider=requested_provider or provider,
    )


__all__ = ["complete_internal_new_pipeline"]
