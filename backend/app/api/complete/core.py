"""Core completion logic for the completion API.

Single composition point for the synchronous ``POST /api/complete`` path:
``setup_completion_session`` → optional ``inject_memory_context`` →
``resolve_llm_model`` → ``orchestrator.run_completion`` → optional
``extract_cited_uuids``. The new pipeline replaces the legacy
``ProviderAdapter`` family + capability-aware routing; the unified tool
loop runs server-side via ``app.llm.tool_loop`` with
``app.services.tools.create_direct_handler`` as the runner.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

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
from .schemas import MessageInput  # re-export for back-compat callers
from .session_repo import (
    get_or_create_session,  # re-export for back-compat callers
    setup_completion_session,
)
from .streaming import stream_completion  # re-export for back-compat callers
from .tool_handlers import AgentProgress
from .types import CompletionInternalResult

logger = logging.getLogger(__name__)


def _assistant_text(message: AssistantMessage) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "".join(parts)


def _assistant_thinking(message: AssistantMessage) -> tuple[str | None, int | None]:
    chunks: list[str] = []
    for block in message.content:
        if isinstance(block, ThinkingContent) and block.thinking:
            chunks.append(block.thinking)
    if not chunks:
        return None, None
    thinking = "\n".join(chunks)
    return thinking, len(thinking) // 4


def _assistant_tool_calls(message: AssistantMessage) -> list[ToolCall]:
    return [block for block in message.content if isinstance(block, ToolCall)]


def _make_tool_runner(
    *,
    working_dir: str | None,
    project_id: str | None,
    session_id: str | None,
    agent_slug: str | None,
) -> ToolRunner:
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


async def complete_internal(
    messages: list[dict[str, Any]], model: str, provider: str,
    temperature: float, project_id: str, db: AsyncSession | None,
    session_id: str | None = None, external_id: str | None = None,
    client_id: str | None = None, request_source: str | None = None,
    parent_session_id: str | None = None,
    agent_slug: str | None = None, use_memory: bool = False,
    memory_group_id: str | None = None, enable_caching: bool = True,
    cache_ttl: str = "ephemeral", thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    enable_programmatic_tools: bool = False,
    defer_tool_loading: bool = False,
    container_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    skip_cache: bool = False,
    user_messages_for_db: list[MessageInput] | None = None,
    max_turns: int = 1, execute_tools: bool = False,
    working_dir: str | None = None,
    progress_callback: Callable[[AgentProgress], Any] | None = None,
    trace_id: str | None = None,
    task_type: str | None = None, phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    requested_model: str | None = None,
    requested_provider: str | None = None,
) -> CompletionInternalResult:
    """Run a completion via the unified ``app.llm`` pipeline.

    When ``db`` is ``None`` the call runs ephemerally: no session row is
    created, no DB-backed memory injection is attempted, and the returned
    ``session_id`` is a synthetic ``ephemeral:<uuid>``. The agentic path
    always supplies a real ``AsyncSession``.
    """

    if db is not None:
        _session, session_id, _is_new, messages_dict = await setup_completion_session(
            db, session_id, project_id, provider, model,
            external_id, client_id, request_source, agent_slug, current_branch, working_dir,
            parent_session_id, messages, trace_id=trace_id,
            requested_provider=requested_provider or provider,
            requested_model=requested_model or model,
        )
    else:
        session_id = session_id or f"ephemeral:{uuid4()}"
        messages_dict = list(messages)

    loaded_memory_uuids: list[str] = []
    if use_memory and db is not None:
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

    result = await run_completion(
        llm_model,
        context,
        execute_tools=execute_tools,
        run_tool=run_tool,
        max_turns=max_turns,
    )
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


__all__ = [
    "AgentProgress",
    "CompletionInternalResult",
    "complete_internal",
    "get_or_create_session",
    "stream_completion",
]
