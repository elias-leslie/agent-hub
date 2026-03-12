"""Shared execution loop entrypoint for completion orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.response_cache import get_response_cache

from .execution_observability import persist_execution_observability
from .helpers import get_adapter
from .multi_turn_executor import execute_multi_turn
from .result_builder import build_completion_result
from .result_finalizer import finalize_completion_result
from .schemas import MessageInput
from .session_manager import apply_execution_metadata
from .tool_handlers import AgentProgress
from .tool_router import route_tool_execution
from .turn_budget import resolve_tool_max_turns
from .types import CompletionInternalResult


@dataclass
class AgentLoopRequest:
    """Execution context for the shared agent loop entrypoint."""

    provider: str
    messages_dict: list[dict[str, Any]]
    user_messages_for_db: list[MessageInput]
    model: str
    temperature: float
    db: AsyncSession
    session: Any
    session_id: str
    is_new_session: bool
    loaded_memory_uuids: list[str]
    memory_group_id: str | None
    skip_cache: bool
    progress_callback: Callable[[AgentProgress], Any] | None
    max_turns: int
    project_id: str
    tools: list[dict[str, Any]] | None = None
    tool_catalog: list[dict[str, Any]] | None = None
    working_dir: str | None = None
    permission_config: dict[str, Any] | None = None
    enable_programmatic_tools: bool = False
    defer_tool_loading: bool = False
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"
    thinking_level: str | None = None
    container_id: str | None = None
    response_format: dict[str, Any] | None = None
    agent_slug: str | None = None
    task_type: str | None = None


async def _execute_tool_loop(req: AgentLoopRequest) -> CompletionInternalResult:
    effective_tool_turn_budget = resolve_tool_max_turns(req.provider, req.max_turns)
    tool_result_dict = await route_tool_execution(
        provider=req.provider,
        messages_dict=req.messages_dict,
        user_messages_for_db=req.user_messages_for_db,
        model=req.model,
        temperature=req.temperature,
        tools=req.tools,
        tool_catalog=req.tool_catalog,
        working_dir=req.working_dir,
        permission_config=req.permission_config,
        db=req.db,
        session=req.session,
        session_id=req.session_id,
        is_new_session=req.is_new_session,
        loaded_memory_uuids=req.loaded_memory_uuids,
        memory_group_id=req.memory_group_id,
        skip_cache=req.skip_cache,
        progress_callback=req.progress_callback,
        max_turns=effective_tool_turn_budget,
        project_id=req.project_id,
    )
    effective_model = tool_result_dict.get("model_used") or req.model
    apply_execution_metadata(
        req.session,
        requested_model=req.model,
        effective_model=effective_model,
        fallback_used=bool(tool_result_dict.get("fallback_used", False)),
        fallback_reason=tool_result_dict.get("fallback_reason"),
    )
    await persist_execution_observability(
        req.db,
        req.session,
        req.session_id,
        provider=req.provider,
        model_used=effective_model,
        requested_max_turns=req.max_turns,
        orchestration_path="tool_loop",
        final_finish_reason=tool_result_dict.get("finish_reason"),
        execution_status=tool_result_dict.get("status"),
        execution_error=tool_result_dict.get("error"),
        turns_completed=tool_result_dict.get("turns"),
        tool_calls_count=tool_result_dict.get("tool_calls_count", 0),
    )
    await req.db.commit()
    return CompletionInternalResult(**tool_result_dict)


async def _execute_multi_turn_loop(req: AgentLoopRequest) -> CompletionInternalResult:
    cache = get_response_cache()
    exec_result = await execute_multi_turn(
        adapter=get_adapter(req.provider),
        messages_dict=req.messages_dict,
        model=req.model,
        provider=req.provider,
        temperature=req.temperature,
        max_turns=req.max_turns,
        enable_caching=req.enable_caching,
        cache_ttl=req.cache_ttl,
        thinking_level=req.thinking_level,
        tools=req.tools,
        enable_programmatic_tools=req.enable_programmatic_tools,
        container_id=req.container_id,
        response_format=req.response_format,
        working_dir=req.working_dir,
        db=req.db,
        session_id=req.session_id,
        user_messages_for_db=req.user_messages_for_db,
        skip_cache=req.skip_cache,
        cache=cache,
        loaded_memory_uuids=req.loaded_memory_uuids,
        memory_group_id=req.memory_group_id,
        progress_callback=req.progress_callback,
        agent_slug=req.agent_slug,
        task_type=req.task_type,
    )
    final_result = exec_result["final_result"]
    effective_model = getattr(final_result, "model_used", None) or req.model
    await finalize_completion_result(
        req.db,
        req.session,
        req.session_id,
        req.model,
        effective_model,
        req.provider,
        exec_result["total_input_tokens"],
        exec_result["total_output_tokens"],
        req.is_new_session,
        final_result,
        project_id=req.project_id,
        fallback_used=bool(getattr(final_result, "fallback_used", False)),
        fallback_reason=getattr(final_result, "fallback_reason", None),
        requested_max_turns=req.max_turns,
        orchestration_path="multi_turn",
        execution_status=exec_result["execution_status"],
        execution_error=exec_result["execution_error"],
    )
    result_dict = build_completion_result(
        final_content=exec_result["final_content"],
        model=req.model,
        provider=req.provider,
        total_input_tokens=exec_result["total_input_tokens"],
        total_output_tokens=exec_result["total_output_tokens"],
        final_finish_reason=exec_result["final_finish_reason"],
        final_session_id=req.session_id,
        loaded_memory_uuids=req.loaded_memory_uuids,
        cited_uuids_list=exec_result["cited_uuids_list"],
        total_thinking_tokens=exec_result["total_thinking_tokens"],
        tool_calls_count=exec_result["tool_calls_count"],
        execution_status=exec_result["execution_status"],
        execution_error=exec_result["execution_error"],
        current_container_id=exec_result["current_container_id"],
        progress_log=exec_result["progress_log"],
        final_result=final_result,
    )
    return CompletionInternalResult(**result_dict)


async def execute_agent_loop(
    req: AgentLoopRequest,
    *,
    should_execute_tools: bool,
) -> CompletionInternalResult:
    """Run the shared execution loop for both tool and non-tool completions."""
    if should_execute_tools:
        return await _execute_tool_loop(req)
    return await _execute_multi_turn_loop(req)
