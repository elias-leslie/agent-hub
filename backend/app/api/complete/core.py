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
import re
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
from app.routing.registry import is_workload_provider
from app.services.llm_errors import ProviderError
from app.services.tools.base import ToolCall as ServiceToolCall
from app.services.tools.base import ToolCaller
from app.services.tools.tool_handler import create_direct_handler

from .orchestrator import build_context_from_messages, run_completion
from .progress import AgentProgress
from .schemas import MessageInput  # re-export for back-compat callers
from .session_repo import (
    get_or_create_session,  # re-export for back-compat callers
    setup_completion_session,
)
from .streaming import stream_completion  # re-export for back-compat callers
from .types import CompletionInternalResult

logger = logging.getLogger(__name__)

_THINK_OPEN_RE = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


def _split_tagged_thinking(text: str) -> tuple[str, list[str]]:
    """Split provider-emitted ``<think>`` text away from assistant-visible text."""
    output: list[str] = []
    thinking: list[str] = []
    pos = 0
    while pos < len(text):
        open_match = _THINK_OPEN_RE.search(text, pos)
        close_match = _THINK_CLOSE_RE.search(text, pos)
        if close_match is None:
            output.append(text[pos:])
            break
        if open_match is not None and open_match.start() < close_match.start():
            output.append(text[pos:open_match.start()])
            tagged = text[open_match.end():close_match.start()].strip()
        else:
            tagged = text[pos:close_match.start()].strip()
        if tagged:
            thinking.append(tagged)
        pos = close_match.end()
    visible_text = "".join(output)
    if thinking:
        visible_text = visible_text.strip()
    return visible_text, thinking


def _assistant_text_and_tagged_thinking(message: AssistantMessage) -> tuple[str, list[str]]:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return _split_tagged_thinking("".join(parts))


def _normalize_tagged_thinking(message: AssistantMessage) -> None:
    """Move raw provider ``<think>`` text blocks into ThinkingContent blocks."""
    normalized = []
    changed = False
    for block in message.content:
        if not isinstance(block, TextContent):
            normalized.append(block)
            continue
        text, thinking_chunks = _split_tagged_thinking(block.text)
        if thinking_chunks:
            changed = True
            normalized.extend(ThinkingContent(thinking=chunk) for chunk in thinking_chunks)
        if text:
            normalized.append(TextContent(text=text, text_signature=block.text_signature))
    if changed:
        message.content = normalized


def _assistant_thinking(
    message: AssistantMessage,
    tagged_thinking: list[str],
) -> tuple[str | None, int | None]:
    chunks: list[str] = []
    for block in message.content:
        if isinstance(block, ThinkingContent) and block.thinking:
            chunks.append(block.thinking)
    chunks.extend(tagged_thinking)
    if not chunks:
        return None, None
    thinking = "\n".join(chunks)
    return thinking, len(thinking) // 4


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
    max_turns: int | None = None, execute_tools: bool = False,
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

    if not is_workload_provider(provider):
        raise ProviderError(
            provider=provider,
            message=(
                "Claude/Anthropic models are catalog references and external "
                "Claude Code TUI only; Agent Hub workloads must use a routable provider."
            ),
            status_code=400,
        )

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
    context = build_context_from_messages(messages_dict, tools=tools)

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
    _normalize_tagged_thinking(message)

    content, tagged_thinking = _assistant_text_and_tagged_thinking(message)
    thinking_content, thinking_tokens = _assistant_thinking(message, tagged_thinking)
    cited_uuids = await extract_cited_uuids(content, memory_group_id) if use_memory else []

    return CompletionInternalResult(
        message=message,
        finish_reason=message.stop_reason,
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
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
