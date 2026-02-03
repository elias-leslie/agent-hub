"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import Message, ProviderError
from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.context_tracker import log_token_usage
from app.services.event_storage import (
    get_sequencer,
    store_memory_cite_event,
    store_memory_inject_event,
    store_message_event,
    store_thinking_event,
    store_tool_result_event,
    store_tool_use_event,
)
from app.services.events import (
    publish_complete,
    publish_message,
    publish_session_start,
)
from app.services.memory import (
    extract_uuid_prefixes,
    inject_progressive_context,
    parse_memory_group_id,
    resolve_full_uuids,
    track_loaded_batch,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import estimate_cost

from .helpers import (
    get_adapter,
    is_error_response,
    normalize_content_for_storage,
)
from .schemas import MessageInput, StreamingChunk

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class AgentProgress:
    """Progress update during agent execution."""

    turn: int
    status: str
    message: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None


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


async def get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str = "completion",
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
) -> tuple[DBSession, list[Message], bool]:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    if session_id:
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.events))
            .where(DBSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            models_used = session.models_used or []
            providers_used = session.providers_used or []
            if model not in models_used:
                models_used.append(model)
                session.models_used = models_used
            if provider not in providers_used:
                providers_used.append(provider)
                session.providers_used = providers_used
            if agent_slug and not session.agent_slug:
                session.agent_slug = agent_slug
            await db.commit()

            context_messages = [
                Message(role=e.role, content=e.content)
                for e in sorted(session.events, key=lambda x: (x.turn, x.sequence))
                if e.event_type
                in (
                    SessionEventType.USER_MESSAGE,
                    SessionEventType.ASSISTANT_MESSAGE,
                    SessionEventType.SYSTEM_MESSAGE,
                )
                and e.role
                and e.content
            ]

            max_turn = max((e.turn for e in session.events), default=0)
            if max_turn > 0:
                get_sequencer().set_turn(session.id, max_turn + 1)

            return session, context_messages, False

    new_session_id = session_id or str(uuid.uuid4())
    session = DBSession(
        id=new_session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
        models_used=[model],
        providers_used=[provider],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, [], True


async def save_events(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    assistant_content: str,
    input_tokens: int,
    output_tokens: int,
    model_used: str | None = None,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
) -> None:
    """Save user messages, thinking, and assistant response as events."""
    for msg in user_messages:
        if msg.role in ("user", "system"):
            await store_message_event(
                db=db,
                session_id=session_id,
                role=msg.role,
                content=normalize_content_for_storage(msg.content),
            )

    if thinking_content:
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=thinking_content,
            tokens=thinking_tokens,
            model_used=model_used,
        )

    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        tokens=output_tokens,
        model_used=model_used,
    )
    await db.commit()


async def update_provider_metadata(
    db: AsyncSession,
    session: DBSession,
    cache_metrics: dict[str, Any] | None,
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return

    # Merge with existing metadata
    existing = session.provider_metadata or {}
    existing["cache"] = {
        "last_cache_creation_tokens": cache_metrics.get("cache_creation_input_tokens", 0),
        "last_cache_read_tokens": cache_metrics.get("cache_read_input_tokens", 0),
        "total_cache_creation_tokens": existing.get("cache", {}).get(
            "total_cache_creation_tokens", 0
        )
        + cache_metrics.get("cache_creation_input_tokens", 0),
        "total_cache_read_tokens": existing.get("cache", {}).get("total_cache_read_tokens", 0)
        + cache_metrics.get("cache_read_input_tokens", 0),
    }
    session.provider_metadata = existing
    await db.commit()


async def _complete_with_claude_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[Any] | None,
    model: str,
    provider: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None,
) -> CompletionInternalResult:
    """Execute completion using Claude's complete_with_tools() for full observability.

    This runs the full agentic loop via Claude Agent SDK, which:
    1. Executes tools automatically
    2. Invokes PostToolUse hooks for observability callbacks
    3. Yields SDK events that we process to build the result
    """
    from claude_agent_sdk.types import AssistantMessage, TextBlock, UserMessage

    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_count = 0
    progress_log: list[AgentProgress] = []
    sdk_session_id: str | None = None

    # Store user messages FIRST (before tool events from SDK loop)
    if messages_for_db:
        for msg in messages_for_db:
            if msg.role in ("user", "system"):
                await store_message_event(
                    db=db,
                    session_id=session_id,
                    role=msg.role,
                    content=normalize_content_for_storage(msg.content),
                )
                content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                await publish_message(session_id, msg.role, content_str)
        await db.commit()

    # Map permission_config to Claude SDK params
    # YOLO mode (default): auto-approve all tools including writes
    # GRANULAR mode: use allow_list to determine write_enabled
    yolo_mode = True  # Default: auto-approve all
    write_enabled = True  # Default: allow write tools
    if permission_config:
        mode = permission_config.get("mode", "yolo")
        if mode == "granular":
            yolo_mode = False
            allow_list = set(permission_config.get("allow_list", []))
            deny_list = set(permission_config.get("deny_list", []))
            # Write tools allowed if any write tool in allow_list and not in deny_list
            write_tools = {"write_file", "edit_file", "delete_file", "create_directory"}
            write_enabled = bool(allow_list & write_tools) and not bool(deny_list & write_tools)

    try:
        turn = 0
        async for msg, sess_id in adapter.complete_with_tools(
            messages=messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            write_enabled=write_enabled,
            yolo_mode=yolo_mode,
        ):
            if sess_id and not sdk_session_id:
                sdk_session_id = sess_id
                logger.info(f"Claude SDK session: {sdk_session_id}")

            msg_type = type(msg).__name__

            # Extract thinking blocks
            if msg_type == "ThinkingBlock" or (hasattr(msg, "type") and msg.type == "thinking"):
                thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
                if thinking_text:
                    thinking_parts.append(thinking_text)

            # Track tool use for progress reporting AND store event
            if msg_type == "ToolUseBlock" or (hasattr(msg, "type") and msg.type == "tool_use"):
                tool_calls_count += 1
                tool_name = getattr(msg, "name", "unknown")
                tool_input = getattr(msg, "input", {})

                # Store tool_use event for observability
                await store_tool_use_event(
                    db,
                    session_id,
                    tool_name=tool_name,
                    tool_input=tool_input
                    if isinstance(tool_input, dict)
                    else {"value": tool_input},
                )

                progress = AgentProgress(
                    turn=turn,
                    status="tool_use",
                    message=f"Using tool: {tool_name}",
                    tool_calls=[{"name": tool_name, "input": tool_input}],
                )
                progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)

            # Extract text content from AssistantMessage
            if isinstance(msg, AssistantMessage):
                turn += 1
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)
                    block_type = type(block).__name__
                    if block_type == "ThinkingBlock" or getattr(block, "type", "") == "thinking":
                        thinking_text = getattr(block, "thinking", "") or getattr(block, "text", "")
                        if thinking_text and thinking_text not in thinking_parts:
                            thinking_parts.append(thinking_text)
                    # Check for ToolUseBlock inside AssistantMessage content
                    if block_type == "ToolUseBlock" or getattr(block, "type", "") == "tool_use":
                        tool_calls_count += 1
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        # Store tool_use event for observability
                        await store_tool_use_event(
                            db,
                            session_id,
                            tool_name=tool_name,
                            tool_input=tool_input
                            if isinstance(tool_input, dict)
                            else {"value": tool_input},
                        )
                        progress = AgentProgress(
                            turn=turn,
                            status="tool_use",
                            message=f"Using tool: {tool_name}",
                            tool_calls=[{"name": tool_name, "input": tool_input}],
                        )
                        progress_log.append(progress)
                        if progress_callback:
                            await progress_callback(progress)

            # Handle init message for session ID
            if hasattr(msg, "subtype") and msg.subtype == "init":
                init_data = getattr(msg, "data", {})
                if init_data.get("session_id"):
                    sdk_session_id = init_data["session_id"]

            # Handle UserMessage (contains tool results from SDK)
            if isinstance(msg, UserMessage) and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__
                    # ToolResultBlock contains tool execution results
                    if block_type == "ToolResultBlock":
                        result_content = getattr(block, "content", "")
                        is_error = getattr(block, "is_error", False)
                        tool_use_id = getattr(block, "tool_use_id", "")
                        # Store tool_result event for observability
                        await store_tool_result_event(
                            db,
                            session_id,
                            tool_name=tool_use_id,
                            tool_output={
                                "content": str(result_content)[:2000] if result_content else "",
                                "is_error": is_error,
                            },
                        )

    except Exception as e:
        logger.exception(f"Claude complete_with_tools error: {e}")
        return CompletionInternalResult(
            content=f"Error: {e}",
            model=model,
            provider=provider,
            input_tokens=0,
            output_tokens=0,
            finish_reason="error",
            session_id=session_id,
            memory_uuids=loaded_memory_uuids,
            cited_uuids=[],
            status="error",
            error=str(e),
        )

    final_content = "".join(content_parts)
    thinking_content = "\n".join(thinking_parts) if thinking_parts else None
    estimated_output_tokens = len(final_content) // 4
    thinking_tokens = len(thinking_content) // 4 if thinking_content else None

    # Store thinking event if present (user messages already stored before SDK loop)
    if thinking_content:
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=thinking_content,
            tokens=thinking_tokens,
            model_used=model,
        )

    # Store assistant response
    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=final_content,
        tokens=estimated_output_tokens,
        model_used=model,
    )
    await publish_message(session_id, "assistant", final_content, estimated_output_tokens)

    # Track citations
    cited_uuids: list[str] = []
    if loaded_memory_uuids and final_content:
        try:
            cited_prefixes = extract_uuid_prefixes(final_content)
            if cited_prefixes:
                scope, scope_id = parse_memory_group_id(memory_group_id)
                group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                cited_uuids = list(prefix_to_uuid.values())
                if cited_uuids:
                    await track_referenced_batch(cited_uuids)
                    await store_memory_cite_event(db, session_id, cited_uuids)
                    logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
        except Exception as e:
            logger.warning(f"Citation tracking failed (continuing): {e}")

    # Log token usage
    cost = estimate_cost(0, estimated_output_tokens, model)
    await log_token_usage(db, session_id, model, 0, estimated_output_tokens, cost.total_cost_usd)
    await publish_complete(session_id, 0, estimated_output_tokens, cost.total_cost_usd)

    # Mark session completed
    if is_new_session:
        session.status = "completed"

    await db.commit()

    progress = AgentProgress(
        turn=turn,
        status="complete",
        message=f"Completed with {tool_calls_count} tool calls",
    )
    progress_log.append(progress)
    if progress_callback:
        await progress_callback(progress)

    return CompletionInternalResult(
        content=final_content,
        model=model,
        provider=provider,
        input_tokens=0,
        output_tokens=estimated_output_tokens,
        finish_reason="end_turn",
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turns=turn or 1,
        tool_calls_count=tool_calls_count,
        status="success",
        progress_log=progress_log,
    )


async def _complete_with_gemini_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[Any] | None,
    model: str,
    provider: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    working_dir: str | None,
    max_turns: int,
    permission_config: dict[str, Any] | None,
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    skip_cache: bool,
    progress_callback: Callable[[AgentProgress], Any] | None,
) -> CompletionInternalResult:
    """Execute completion using Gemini's complete_with_tools() for full observability.

    This runs the agentic loop with actual tool execution, storing both
    tool_use AND tool_result events for full observability.
    """
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    tool_calls_count = 0
    progress_log: list[AgentProgress] = []
    turn = 0

    # Store user messages FIRST (before tool events from agentic loop)
    if messages_for_db:
        for msg in messages_for_db:
            if msg.role in ("user", "system"):
                await store_message_event(
                    db=db,
                    session_id=session_id,
                    role=msg.role,
                    content=normalize_content_for_storage(msg.content),
                )
                content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                await publish_message(session_id, msg.role, content_str)
        await db.commit()

    try:
        async for event, _gemini_session_id in adapter.complete_with_tools(
            messages=messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            max_turns=max_turns,
            permission_config=permission_config,
        ):
            event_type = getattr(event, "type", None)

            # Process assistant messages (text content and tool_use blocks)
            if event_type == "assistant":
                message = getattr(event, "message", None)
                if message:
                    for block in getattr(message, "content", []):
                        block_type = getattr(block, "type", None)
                        if block_type == "text":
                            text = getattr(block, "text", "")
                            if text:
                                content_parts.append(text)
                        elif block_type == "tool_use":
                            tool_calls_count += 1
                            tool_name = getattr(block, "name", "unknown")
                            tool_input = getattr(block, "input", {})
                            _tool_id = getattr(block, "id", "")

                            # Store tool_use event
                            await store_tool_use_event(
                                db,
                                session_id,
                                tool_name=tool_name,
                                tool_input=tool_input
                                if isinstance(tool_input, dict)
                                else {"value": tool_input},
                            )

                            # Progress callback
                            progress = AgentProgress(
                                turn=turn,
                                status="tool_use",
                                message=f"Using tool: {tool_name}",
                                tool_calls=[{"name": tool_name, "input": tool_input}],
                            )
                            progress_log.append(progress)
                            if progress_callback:
                                await progress_callback(progress)

            # Process tool_result events - THIS IS KEY FOR FULL OBSERVABILITY
            elif event_type == "tool_result":
                tool_content = getattr(event, "content", "")
                tool_use_id = getattr(event, "tool_use_id", "")
                is_error = getattr(event, "is_error", False)

                # Store tool_result event
                await store_tool_result_event(
                    db,
                    session_id,
                    tool_name=tool_use_id,  # Use tool_use_id as reference
                    tool_output={
                        "content": tool_content[:2000] if tool_content else "",
                        "is_error": is_error,
                    },
                )
                turn += 1

            # Process result event (completion)
            elif event_type == "result":
                result_text = getattr(event, "result", "")
                if result_text and result_text not in "".join(content_parts):
                    content_parts.append(result_text)

            # Process error event
            elif event_type == "error":
                error_msg = getattr(event, "error", "Unknown error")
                logger.error(f"Gemini tool execution error: {error_msg}")
                return CompletionInternalResult(
                    content=f"Error: {error_msg}",
                    model=model,
                    provider=provider,
                    input_tokens=0,
                    output_tokens=0,
                    finish_reason="error",
                    session_id=session_id,
                    memory_uuids=loaded_memory_uuids,
                    cited_uuids=[],
                    status="error",
                    error=error_msg,
                )

        await db.commit()

    except Exception as e:
        logger.exception(f"Gemini complete_with_tools error: {e}")
        return CompletionInternalResult(
            content=f"Error: {e}",
            model=model,
            provider=provider,
            input_tokens=0,
            output_tokens=0,
            finish_reason="error",
            session_id=session_id,
            memory_uuids=loaded_memory_uuids,
            cited_uuids=[],
            status="error",
            error=str(e),
        )

    final_content = "".join(content_parts)
    estimated_output_tokens = len(final_content) // 4

    # Store assistant response
    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=final_content,
        tokens=estimated_output_tokens,
        model_used=model,
    )
    await publish_message(session_id, "assistant", final_content, estimated_output_tokens)

    # Track citations
    cited_uuids: list[str] = []
    if loaded_memory_uuids and final_content:
        try:
            cited_prefixes = extract_uuid_prefixes(final_content)
            if cited_prefixes:
                scope, scope_id = parse_memory_group_id(memory_group_id)
                group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                cited_uuids = list(prefix_to_uuid.values())
                if cited_uuids:
                    await track_referenced_batch(cited_uuids)
                    await store_memory_cite_event(db, session_id, cited_uuids)
                    logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
        except Exception as e:
            logger.warning(f"Citation tracking failed (continuing): {e}")

    # Log token usage
    cost = estimate_cost(0, estimated_output_tokens, model)
    await log_token_usage(db, session_id, model, 0, estimated_output_tokens, cost.total_cost_usd)
    await publish_complete(session_id, 0, estimated_output_tokens, cost.total_cost_usd)

    # Mark session completed
    if is_new_session:
        session.status = "completed"

    await db.commit()

    progress = AgentProgress(
        turn=turn or 1,
        status="complete",
        message=f"Completed with {tool_calls_count} tool calls",
    )
    progress_log.append(progress)
    if progress_callback:
        await progress_callback(progress)

    return CompletionInternalResult(
        content=final_content,
        model=model,
        provider=provider,
        input_tokens=0,
        output_tokens=estimated_output_tokens,
        finish_reason="end_turn",
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        turns=turn or 1,
        tool_calls_count=tool_calls_count,
        status="success",
        progress_log=progress_log,
    )


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

        return await _complete_with_claude_tools(
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

    if should_execute_tools and provider == "gemini":
        from app.adapters.gemini import GeminiAdapter

        gemini_adapter = GeminiAdapter()

        return await _complete_with_gemini_tools(
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
        )

    adapter = get_adapter(provider)

    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages_dict]

    # Multi-turn execution state
    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0
    tool_calls_count = 0
    progress_log: list[AgentProgress] = []
    all_cited_uuids: set[str] = set()
    final_content = ""
    final_finish_reason: str | None = None
    final_result: Any = None
    current_container_id = container_id
    execution_status = "success"
    execution_error: str | None = None

    # Register container manager for multi-turn execution
    from app.services.container_manager import ContainerManager

    container_manager = ContainerManager()

    try:
        for turn in range(1, max_turns + 1):
            # Report progress
            progress = AgentProgress(
                turn=turn,
                status="running",
                message=f"Turn {turn}: sending to {provider}",
            )
            progress_log.append(progress)
            if progress_callback:
                await progress_callback(progress)

            # Get completion
            result = await adapter.complete(
                messages=messages_for_adapter,
                model=model,
                max_tokens=None,
                temperature=temperature,
                enable_caching=enable_caching if turn == 1 else False,
                cache_ttl=cache_ttl,
                thinking_level=thinking_level,
                tools=tools,
                enable_programmatic_tools=enable_programmatic_tools,
                container_id=current_container_id,
                response_format=response_format,
                working_dir=working_dir,
            )

            # Track tokens
            total_input_tokens += result.input_tokens
            total_output_tokens += result.output_tokens
            if result.thinking_tokens:
                total_thinking_tokens += result.thinking_tokens

            # Track container
            if result.container:
                current_container_id = result.container.id
                container_manager.register(
                    result.container.id, result.container.expires_at, final_session_id
                )

            final_content = result.content
            final_finish_reason = result.finish_reason
            final_result = result

            # Store events for turn 1 (user messages, thinking, assistant response)
            if turn == 1:
                if user_messages_for_db:
                    await save_events(
                        db,
                        final_session_id,
                        user_messages_for_db,
                        result.content,
                        result.input_tokens,
                        result.output_tokens,
                        model_used=model,
                        thinking_content=result.thinking_content,
                        thinking_tokens=result.thinking_tokens,
                    )
                    for msg in user_messages_for_db:
                        if msg.role in ("user", "system"):
                            content_str = (
                                msg.content if isinstance(msg.content, str) else str(msg.content)
                            )
                            await publish_message(final_session_id, msg.role, content_str)
                    await publish_message(
                        final_session_id, "assistant", result.content, result.output_tokens
                    )

                # Cache first turn response if successful
                if not skip_cache and not is_error_response(result.content):
                    await cache.set(
                        model=model,
                        messages=messages_dict,
                        temperature=temperature,
                        content=result.content,
                        provider=result.provider,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        finish_reason=result.finish_reason,
                    )

                # Track citations from first turn
                if loaded_memory_uuids and result.content:
                    try:
                        cited_prefixes = extract_uuid_prefixes(result.content)
                        if cited_prefixes:
                            scope, scope_id = parse_memory_group_id(memory_group_id)
                            group_id = (
                                "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                            )
                            prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                            all_cited_uuids.update(prefix_to_uuid.values())
                    except Exception as e:
                        logger.warning(f"Citation tracking failed (continuing): {e}")

            else:
                # For turns > 1, advance sequencer and store events
                get_sequencer().next_turn(final_session_id)

                if result.thinking_content:
                    await store_thinking_event(
                        db,
                        final_session_id,
                        result.thinking_content,
                        tokens=result.thinking_tokens,
                        model_used=model,
                    )

                if result.content:
                    await store_message_event(
                        db,
                        final_session_id,
                        role="assistant",
                        content=result.content,
                        tokens=result.output_tokens,
                        model_used=model,
                    )

                # Track citations from subsequent turns
                if result.content:
                    try:
                        cited_prefixes = extract_uuid_prefixes(result.content)
                        if cited_prefixes:
                            scope, scope_id = parse_memory_group_id(memory_group_id)
                            group_id = (
                                "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                            )
                            prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                            all_cited_uuids.update(prefix_to_uuid.values())
                    except Exception as e:
                        logger.warning(f"Citation tracking failed (continuing): {e}")

            # Store tool use events for all turns
            for tc in result.tool_calls or []:
                await store_tool_use_event(
                    db,
                    final_session_id,
                    tool_name=tc.name,
                    tool_input=tc.input if isinstance(tc.input, dict) else {"value": tc.input},
                )
            await db.commit()

            # Check finish reason
            if result.finish_reason == "end_turn":
                progress = AgentProgress(
                    turn=turn,
                    status="complete",
                    message="Agent completed task",
                )
                progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)
                break

            elif result.finish_reason == "tool_use":
                # Model requested tool execution but execute_tools is False
                # Return immediately with tool_calls populated - caller must handle
                tool_calls_count = len(result.tool_calls or [])
                progress = AgentProgress(
                    turn=turn,
                    status="tool_use_requested",
                    message=f"Model requested {tool_calls_count} tool(s) - requires execute_tools=True",
                    tool_calls=[
                        {"name": tc.name, "input": tc.input} for tc in (result.tool_calls or [])
                    ],
                )
                progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)
                # Stop loop - tools are not being executed, return result for caller
                break

            elif result.finish_reason == "max_tokens":
                execution_status = "error"
                execution_error = "Response truncated due to max_tokens"
                break

            else:
                # Unknown finish reason or None - continue if more turns available
                if turn == max_turns:
                    execution_status = "max_turns"
                    execution_error = f"Reached maximum turns ({max_turns})"
                else:
                    messages_for_adapter.extend(
                        [
                            Message(role="assistant", content=result.content),
                            Message(role="user", content="Please continue."),
                        ]
                    )

    except ProviderError as e:
        execution_status = "error"
        execution_error = str(e)
        logger.exception(f"Provider error during multi-turn execution: {e}")

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

    # Track all cited UUIDs
    cited_uuids_list = list(all_cited_uuids)
    if cited_uuids_list:
        await track_referenced_batch(cited_uuids_list)
        await store_memory_cite_event(db, final_session_id, cited_uuids_list)
        logger.info(f"complete_internal: tracked {len(cited_uuids_list)} cited memory rules")

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


async def stream_completion(
    messages: list[Message],
    model: str,
    provider: str,
    temperature: float,
    session_id: str,
    agent_used: str | None = None,
    model_used: str | None = None,
    fallback_used: bool = False,
    max_tokens: int | None = None,
    db: AsyncSession | None = None,
    user_messages: list[MessageInput] | None = None,
    is_new_session: bool = False,
    is_one_shot: bool = False,
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    Yields:
        SSE formatted strings: "data: {json}\n\n"
    """
    adapter = get_adapter(provider)

    input_tokens = 0
    output_tokens = 0
    accumulated_content = ""

    try:
        async for event in adapter.stream(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if event.type == "content":
                accumulated_content += event.content or ""
                chunk = StreamingChunk(type="content", content=event.content)
                yield f"data: {chunk.model_dump_json()}\n\n"

            elif event.type == "done":
                # Capture final token counts
                if event.input_tokens is not None:
                    input_tokens = event.input_tokens
                if event.output_tokens is not None:
                    output_tokens = event.output_tokens

                # Save messages to database
                if db and user_messages and accumulated_content:
                    try:
                        await save_events(
                            db=db,
                            session_id=session_id,
                            user_messages=user_messages,
                            assistant_content=accumulated_content,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model_used=model,
                        )
                        logger.info(f"Streaming: saved messages for session {session_id}")
                    except Exception as save_err:
                        logger.error(f"Failed to save streaming messages: {save_err}")

                # Close one-shot streaming sessions (no continuation expected)
                if db and is_new_session and is_one_shot:
                    try:
                        from sqlalchemy import select

                        result = await db.execute(
                            select(DBSession).where(DBSession.id == session_id)
                        )
                        session = result.scalar_one_or_none()
                        if session:
                            session.status = "completed"
                            await db.commit()
                            logger.info(f"Streaming: closed one-shot session {session_id}")
                    except Exception as close_err:
                        logger.error(f"Failed to close one-shot session: {close_err}")

                # Send final done event with all metadata
                done_chunk = StreamingChunk(
                    type="done",
                    model=model,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=event.finish_reason,
                    session_id=session_id,
                    agent_used=agent_used,
                    model_used=model_used,
                    fallback_used=fallback_used if agent_used else None,
                )
                yield f"data: {done_chunk.model_dump_json()}\n\n"

            elif event.type == "error":
                error_chunk = StreamingChunk(type="error", error=event.error)
                yield f"data: {error_chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_chunk = StreamingChunk(type="error", error=str(e))
        yield f"data: {error_chunk.model_dump_json()}\n\n"

    # Send [DONE] signal (OpenAI compat)
    yield "data: [DONE]\n\n"
