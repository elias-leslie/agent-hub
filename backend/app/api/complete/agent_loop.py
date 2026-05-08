"""Shared execution loop entrypoint for completion orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.registry import get_adapter
from app.services.response_cache import get_response_cache

from .error_summary import build_error_summary
from .multi_turn_executor import execute_multi_turn
from .result_builder import build_completion_result
from .result_finalizer import finalize_completion_result
from .schemas import MessageInput
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
    enable_programmatic_tools: bool = False
    defer_tool_loading: bool = False
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"
    thinking_level: str | None = None
    container_id: str | None = None
    response_format: dict[str, Any] | None = None
    agent_slug: str | None = None
    task_type: str | None = None


@dataclass
class _LoopOutcome:
    """Normalized terminal state for either tool or multi-turn execution."""

    final_result: Any
    final_content: str
    total_input_tokens: int
    total_output_tokens: int
    final_finish_reason: str | None
    cited_uuids_list: list[str]
    total_thinking_tokens: int | None
    tool_calls_count: int
    execution_status: str
    execution_error: str | None
    current_container_id: str | None
    progress_log: list[AgentProgress]


def _normalize_tool_outcome(tool_result_dict: dict[str, Any]) -> _LoopOutcome:
    """Normalize tool execution output to the shared loop outcome shape."""
    progress_log = tool_result_dict.get("progress_log") or []
    final_result = SimpleNamespace(**tool_result_dict)
    return _LoopOutcome(
        final_result=final_result,
        final_content=tool_result_dict["content"],
        total_input_tokens=tool_result_dict.get("input_tokens", 0),
        total_output_tokens=tool_result_dict.get("output_tokens", 0),
        final_finish_reason=tool_result_dict.get("finish_reason"),
        cited_uuids_list=tool_result_dict.get("cited_uuids") or [],
        total_thinking_tokens=tool_result_dict.get("thinking_tokens"),
        tool_calls_count=tool_result_dict.get("tool_calls_count", 0) or 0,
        execution_status=tool_result_dict.get("status", "success"),
        execution_error=tool_result_dict.get("error"),
        current_container_id=tool_result_dict.get("container_id"),
        progress_log=progress_log,
    )


def _normalize_multi_turn_outcome(exec_result: dict[str, Any]) -> _LoopOutcome:
    """Normalize multi-turn execution output to the shared loop outcome shape."""
    return _LoopOutcome(
        final_result=exec_result["final_result"],
        final_content=exec_result["final_content"],
        total_input_tokens=exec_result["total_input_tokens"],
        total_output_tokens=exec_result["total_output_tokens"],
        final_finish_reason=exec_result["final_finish_reason"],
        cited_uuids_list=exec_result["cited_uuids_list"],
        total_thinking_tokens=exec_result["total_thinking_tokens"],
        tool_calls_count=exec_result["tool_calls_count"],
        execution_status=exec_result["execution_status"],
        execution_error=exec_result["execution_error"],
        current_container_id=exec_result["current_container_id"],
        progress_log=exec_result["progress_log"],
    )


async def _finalize_loop_result(
    req: AgentLoopRequest,
    *,
    outcome: _LoopOutcome,
    orchestration_path: str,
) -> CompletionInternalResult:
    """Finalize a normalized loop outcome through the shared completion path."""
    effective_model = getattr(outcome.final_result, "model_used", None) or req.model
    if not getattr(outcome.final_result, "error_summary", None):
        outcome.final_result.error_summary = build_error_summary(
            execution_status=outcome.execution_status,
            execution_error=outcome.execution_error,
            final_finish_reason=outcome.final_finish_reason,
            progress_log=outcome.progress_log,
            tool_result_summaries=getattr(outcome.final_result, "tool_result_summaries", None),
        )
    await finalize_completion_result(
        req.db,
        req.session,
        req.session_id,
        req.model,
        effective_model,
        req.provider,
        outcome.total_input_tokens,
        outcome.total_output_tokens,
        req.is_new_session,
        outcome.final_result,
        project_id=req.project_id,
        fallback_used=bool(getattr(outcome.final_result, "fallback_used", False)),
        fallback_reason=getattr(outcome.final_result, "fallback_reason", None),
        requested_max_turns=req.max_turns,
        orchestration_path=orchestration_path,
        execution_status=outcome.execution_status,
        execution_error=outcome.execution_error,
    )
    result_dict = build_completion_result(
        final_content=outcome.final_content,
        model=req.model,
        provider=req.provider,
        total_input_tokens=outcome.total_input_tokens,
        total_output_tokens=outcome.total_output_tokens,
        final_finish_reason=outcome.final_finish_reason,
        final_session_id=req.session_id,
        loaded_memory_uuids=req.loaded_memory_uuids,
        cited_uuids_list=outcome.cited_uuids_list,
        total_thinking_tokens=outcome.total_thinking_tokens,
        tool_calls_count=outcome.tool_calls_count,
        execution_status=outcome.execution_status,
        execution_error=outcome.execution_error,
        current_container_id=outcome.current_container_id,
        progress_log=outcome.progress_log,
        final_result=outcome.final_result,
    )
    return CompletionInternalResult(**result_dict)


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
    return await _finalize_loop_result(
        req,
        outcome=_normalize_tool_outcome(tool_result_dict),
        orchestration_path="tool_loop",
    )


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
    return await _finalize_loop_result(
        req,
        outcome=_normalize_multi_turn_outcome(exec_result),
        orchestration_path="multi_turn",
    )


async def execute_agent_loop(
    req: AgentLoopRequest,
    *,
    should_execute_tools: bool,
) -> CompletionInternalResult:
    """Run the shared execution loop for both tool and non-tool completions."""
    if should_execute_tools:
        return await _execute_tool_loop(req)
    return await _execute_multi_turn_loop(req)
