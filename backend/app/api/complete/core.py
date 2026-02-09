"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.models import Session as DBSession
from app.services.context_tracker import log_token_usage
from app.services.event_storage import (
    store_memory_inject_event,
    store_tool_result_event,
    store_tool_use_event,
)
from app.services.events import (
    publish_complete,
    publish_session_start,
)
from app.services.memory import (
    inject_progressive_context,
    parse_memory_group_id,
    track_loaded_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import estimate_cost

from .event_helpers import save_events
from .helpers import get_adapter
from .multi_turn_executor import execute_multi_turn
from .schemas import MessageInput
from .session_manager import get_or_create_session, update_provider_metadata
from .streaming import stream_completion  # Re-export for backwards compat
from .tool_handlers import (
    AgentProgress,
    _complete_with_claude_tools,
    _complete_with_gemini_tools,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class CompletionInternalResult:
    """Result from complete_internal() for completion operations."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    session_id: str
    memory_uuids: list[str]
    cited_uuids: list[str]
    from_cache: bool = False
    cache_metrics: Any | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None
    # Multi-turn execution fields
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)


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
    # Multi-turn execution parameters
    max_turns: int = 1,
    execute_tools: bool = False,
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    progress_callback: Callable[[AgentProgress], Any] | None = None,
    trace_id: str | None = None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
) -> CompletionInternalResult:
    """Core completion logic for /complete endpoint.

    Args:
        messages: Conversation messages as dicts with role/content
        model: Model identifier
        provider: Provider name (claude/gemini/openai)
        temperature: Sampling temperature
        project_id: Project ID for session tracking
        db: Database session
        session_id: Optional existing session ID (creates new if None)
        external_id: External ID for cost aggregation
        client_id: Client identifier
        request_source: Request source
        agent_slug: Agent slug for metrics attribution
        use_memory: Whether to inject memory context
        memory_group_id: Memory group for isolation
        enable_caching: Enable prompt caching
        cache_ttl: Cache TTL
        thinking_level: Extended thinking level
        tools: Tool definitions
        enable_programmatic_tools: Enable code execution tools
        container_id: Container ID for code execution
        response_format: Response format spec for JSON mode
        skip_cache: Skip response cache lookup
        user_messages_for_db: Original user messages to save to DB
        task_type: Optional task type for triggered reference injection
        phase: Optional subtask phase for phase-triggered reference injection

    Returns:
        CompletionInternalResult with content, session_id, memory_uuids, cited_uuids
    """
    session: DBSession | None = None
    context_messages: list[Message] = []
    final_session_id = session_id or str(uuid.uuid4())

    session, context_messages, is_new_session = await get_or_create_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        session_type="completion",
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
    )
    final_session_id = session.id

    if is_new_session:
        await publish_session_start(final_session_id, model, project_id)

    messages_dict = list(messages)
    if context_messages:
        context_as_dicts = [{"role": m.role, "content": m.content} for m in context_messages]
        messages_dict = context_as_dicts + messages_dict

    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    if use_memory:
        scope, scope_id = parse_memory_group_id(memory_group_id)
        try:
            messages_dict, progressive_context = await inject_progressive_context(
                messages=messages_dict,
                scope=scope,
                scope_id=scope_id,
                task_type=task_type,
                phase=phase,
                memory_config=memory_config,
            )
            memory_facts_injected = (
                len(progressive_context.mandates)
                + len(progressive_context.guardrails)
                + len(progressive_context.reference)
            )
            loaded_memory_uuids = progressive_context.get_loaded_uuids()
            if memory_facts_injected > 0:
                logger.info(f"complete_internal: injected {memory_facts_injected} memory facts")
                await track_loaded_batch(loaded_memory_uuids)
                await store_memory_inject_event(
                    db, final_session_id, loaded_memory_uuids, memory_facts_injected
                )
        except Exception as e:
            logger.warning(f"Memory injection failed (continuing without): {e}")

    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=model,
            messages=messages_dict,
            temperature=temperature,
        )
        if cached:
            logger.info(f"complete_internal: returning cached response for {model}")
            if user_messages_for_db:
                await save_events(
                    db,
                    final_session_id,
                    user_messages_for_db,
                    cached.content,
                    cached.input_tokens,
                    cached.output_tokens,
                    model_used=model,
                )
            cost = estimate_cost(cached.input_tokens, cached.output_tokens, model)
            await log_token_usage(
                db,
                final_session_id,
                model,
                cached.input_tokens,
                cached.output_tokens,
                cost.total_cost_usd,
            )
            await publish_complete(
                final_session_id, cached.input_tokens, cached.output_tokens, cost.total_cost_usd
            )

            # Mark new sessions as completed (cached single-turn completions are done)
            if is_new_session:
                session.status = "completed"

            await db.commit()
            return CompletionInternalResult(
                content=cached.content,
                model=cached.model,
                provider=cached.provider,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                finish_reason=cached.finish_reason,
                session_id=final_session_id,
                memory_uuids=loaded_memory_uuids,
                cited_uuids=[],
                from_cache=True,
            )

    # For tool execution, auto-provide standard tools if none specified
    # User explicitly enabled tools, so provide bash/read/write by default
    if execute_tools and not tools:
        from app.services.tools.direct_executor import get_standard_tools

        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in get_standard_tools()
        ]
        logger.info(f"Auto-provided {len(tools)} standard tools for execute_tools mode")

    # For tool execution (execute_tools=True or enable_programmatic_tools), use complete_with_tools()
    # This provides full observability with tool_use AND tool_result events
    should_execute_tools = (execute_tools or enable_programmatic_tools) and tools

    if should_execute_tools and provider == "claude":
        from app.adapters.claude import ClaudeAdapter

        async def tool_result_callback(
            tool_name: str, tool_input: dict[str, Any], tool_output: str
        ) -> None:
            await store_tool_use_event(
                db,
                final_session_id,
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {"value": tool_input},
            )
            await store_tool_result_event(
                db,
                final_session_id,
                tool_name=tool_name,
                tool_output={"content": tool_output[:2000] if tool_output else ""},
            )
            await db.commit()

        claude_adapter = ClaudeAdapter(after_tool_callback=tool_result_callback)

        tool_result = await _complete_with_claude_tools(
            adapter=claude_adapter,
            messages=messages_dict,
            messages_for_db=user_messages_for_db,
            model=model,
            provider=provider,
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
        )
        # Convert ToolExecutionResult to CompletionInternalResult
        return CompletionInternalResult(**tool_result.__dict__)

    if should_execute_tools and provider == "gemini":
        from app.adapters.gemini import GeminiAdapter

        gemini_adapter = GeminiAdapter()

        tool_result = await _complete_with_gemini_tools(
            adapter=gemini_adapter,
            messages=messages_dict,
            messages_for_db=user_messages_for_db,
            model=model,
            provider=provider,
            temperature=temperature,
            tools=tools,
            working_dir=working_dir,
            max_turns=max_turns,
            permission_config=permission_config,
            db=db,
            session=session,
            session_id=final_session_id,
            is_new_session=is_new_session,
            loaded_memory_uuids=loaded_memory_uuids,
            memory_group_id=memory_group_id,
            skip_cache=skip_cache,
            progress_callback=progress_callback,
            project_id=project_id,
        )
        # Convert ToolExecutionResult to CompletionInternalResult
        return CompletionInternalResult(**tool_result.__dict__)

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
    )

    # Unpack results
    total_input_tokens = exec_result["total_input_tokens"]
    total_output_tokens = exec_result["total_output_tokens"]
    total_thinking_tokens = exec_result["total_thinking_tokens"]
    tool_calls_count = exec_result["tool_calls_count"]
    progress_log = exec_result["progress_log"]
    cited_uuids_list = exec_result["cited_uuids_list"]
    final_content = exec_result["final_content"]
    final_finish_reason = exec_result["final_finish_reason"]
    final_result = exec_result["final_result"]
    current_container_id = exec_result["current_container_id"]
    execution_status = exec_result["execution_status"]
    execution_error = exec_result["execution_error"]

    # Log token usage and publish completion
    cost = estimate_cost(total_input_tokens, total_output_tokens, model)
    await log_token_usage(
        db, final_session_id, model, total_input_tokens, total_output_tokens, cost.total_cost_usd
    )
    await publish_complete(
        final_session_id, total_input_tokens, total_output_tokens, cost.total_cost_usd
    )

    if final_result and final_result.cache_metrics:
        await update_provider_metadata(
            db,
            session,
            {
                "cache_creation_input_tokens": final_result.cache_metrics.cache_creation_input_tokens,
                "cache_read_input_tokens": final_result.cache_metrics.cache_read_input_tokens,
            },
        )

    # Mark session as completed (unconditionally for new sessions)
    if is_new_session:
        session.status = "completed"

    await db.commit()

    return CompletionInternalResult(
        content=final_content,
        model=model,
        provider=provider,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        finish_reason=final_finish_reason,
        session_id=final_session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids_list,
        from_cache=False,
        cache_metrics=final_result.cache_metrics if final_result else None,
        thinking_content=final_result.thinking_content if final_result else None,
        thinking_tokens=total_thinking_tokens if total_thinking_tokens else None,
        tool_calls=final_result.tool_calls if final_result else None,
        container=final_result.container if final_result else None,
        turns=len([p for p in progress_log if p.status in ("running", "complete", "tool_use")]) // 2
        + 1
        if progress_log
        else 1,
        tool_calls_count=tool_calls_count,
        status=execution_status,
        error=execution_error,
        container_id=current_container_id,
        progress_log=progress_log,
    )


# Re-export stream_completion for backwards compatibility
__all__ = ["AgentProgress", "CompletionInternalResult", "complete_internal", "stream_completion"]
