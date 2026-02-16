"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.response_cache import get_response_cache

from .cache_handler import handle_cached_response
from .helpers import get_adapter
from .memory_handler import inject_memory_context
from .multi_turn_executor import execute_multi_turn
from .result_builder import build_completion_result
from .result_finalizer import finalize_completion_result
from .schemas import MessageInput
from .session_manager import get_or_create_session  # Re-export for backwards compat
from .session_setup import setup_completion_session
from .streaming import stream_completion  # Re-export for backwards compat
from .tool_handlers import AgentProgress
from .tool_provisioner import provision_standard_tools
from .tool_router import route_tool_execution
from .types import CompletionInternalResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def complete_internal(
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    temperature: float,
    project_id: str,
    db: AsyncSession,
    session_id: str | None = None,
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
    use_memory: bool = False,
    memory_group_id: str | None = None,
    enable_caching: bool = True,
    cache_ttl: str = "ephemeral",
    thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    enable_programmatic_tools: bool = False,
    container_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    skip_cache: bool = False,
    user_messages_for_db: list[MessageInput] | None = None,
    max_turns: int = 1,
    execute_tools: bool = False,
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    progress_callback: Callable[[AgentProgress], Any] | None = None,
    trace_id: str | None = None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
) -> CompletionInternalResult:
    """Core completion logic: session setup, memory injection, caching, tool/multi-turn execution."""
    # Auto-derive event storage messages from input when not explicitly provided.
    # This ensures ALL callers get session events tracked without opt-in.
    if user_messages_for_db is None:
        user_messages_for_db = [MessageInput(role=m["role"], content=m["content"]) for m in messages if "role" in m and "content" in m]

    # Setup session and prepare messages
    session, final_session_id, is_new_session, messages_dict = await setup_completion_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        external_id,
        client_id,
        request_source,
        agent_slug,
        messages,
    )

    # Inject memory context if enabled
    loaded_memory_uuids: list[str] = []
    if use_memory:
        messages_dict, loaded_memory_uuids, _ = await inject_memory_context(
            messages_dict, db, final_session_id, memory_group_id, task_type, phase, memory_config,
            current_branch=current_branch, agent_id=agent_slug,
        )

    # Check cache unless skipped
    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(model=model, messages=messages_dict, temperature=temperature)
        if cached:
            cache_result = await handle_cached_response(
                cached, db, session, final_session_id, model, user_messages_for_db, loaded_memory_uuids, is_new_session,
                agent_id=agent_slug,
            )
            return CompletionInternalResult(**cache_result)

    # Auto-provision tools if needed
    tools = provision_standard_tools(execute_tools, tools)

    # Route to tool execution if enabled
    should_execute_tools = (execute_tools or enable_programmatic_tools) and tools
    if should_execute_tools and provider in ("claude", "gemini"):
        tool_result_dict = await route_tool_execution(
            provider=provider,
            messages_dict=messages_dict,
            user_messages_for_db=user_messages_for_db,
            model=model,
            temperature=temperature,
            tools=tools,
            working_dir=working_dir,
            permission_config=permission_config,
            db=db,
            session=session,
            session_id=final_session_id,
            is_new_session=is_new_session,
            loaded_memory_uuids=loaded_memory_uuids,
            memory_group_id=memory_group_id,
            skip_cache=skip_cache,
            progress_callback=progress_callback,
            max_turns=max_turns,
            project_id=project_id,
        )
        return CompletionInternalResult(**tool_result_dict)

    adapter = get_adapter(provider)

    # Execute multi-turn loop
    exec_result = await execute_multi_turn(
        adapter=adapter,
        messages_dict=messages_dict,
        model=model,
        provider=provider,
        temperature=temperature,
        max_turns=max_turns,
        enable_caching=enable_caching,
        cache_ttl=cache_ttl,
        thinking_level=thinking_level,
        tools=tools,
        enable_programmatic_tools=enable_programmatic_tools,
        container_id=container_id,
        response_format=response_format,
        working_dir=working_dir,
        db=db,
        session_id=final_session_id,
        user_messages_for_db=user_messages_for_db,
        skip_cache=skip_cache,
        cache=cache,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        progress_callback=progress_callback,
        agent_slug=agent_slug,
    )

    # Finalize result (token logging, session status, commit)
    await finalize_completion_result(
        db, session, final_session_id, model, exec_result["total_input_tokens"], exec_result["total_output_tokens"], is_new_session, exec_result["final_result"]
    )

    # Build and return final result
    result_dict = build_completion_result(
        final_content=exec_result["final_content"],
        model=model,
        provider=provider,
        total_input_tokens=exec_result["total_input_tokens"],
        total_output_tokens=exec_result["total_output_tokens"],
        final_finish_reason=exec_result["final_finish_reason"],
        final_session_id=final_session_id,
        loaded_memory_uuids=loaded_memory_uuids,
        cited_uuids_list=exec_result["cited_uuids_list"],
        total_thinking_tokens=exec_result["total_thinking_tokens"],
        tool_calls_count=exec_result["tool_calls_count"],
        execution_status=exec_result["execution_status"],
        execution_error=exec_result["execution_error"],
        current_container_id=exec_result["current_container_id"],
        progress_log=exec_result["progress_log"],
        final_result=exec_result["final_result"],
    )
    return CompletionInternalResult(**result_dict)


# Re-export stream_completion for backwards compatibility
__all__ = ["AgentProgress", "CompletionInternalResult", "complete_internal", "get_or_create_session", "stream_completion"]
