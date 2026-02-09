"""Tool execution handlers for Claude and Gemini providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession
from app.services.event_storage import (
    store_message_event,
    store_thinking_event,
    store_tool_result_event,
    store_tool_use_event,
)
from app.services.events import publish_message
from app.services.token_counter import estimate_cost

from .citation_tracker import track_citations
from .helpers import normalize_content_for_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

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
class ToolExecutionResult:
    """Result from tool execution handlers."""

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
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)


async def _complete_with_claude_tools(
    adapter: Any,
    messages: list[dict[str, Any]],
    messages_for_db: list[MessageInput] | None,
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
) -> ToolExecutionResult:
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
                for block in msg.content:  # type: ignore
                    block_type = type(block).__name__
                    # ToolResultBlock contains tool execution results
                    if block_type == "ToolResultBlock":
                        result_content = getattr(block, "content", "")
                        is_error = getattr(block, "is_error", False)
                        tool_use_id = getattr(block, "tool_use_id", "")
                        # Store tool_result event and commit incrementally so events
                        # survive if the agentic loop is interrupted
                        await store_tool_result_event(
                            db,
                            session_id,
                            tool_name=tool_use_id,
                            tool_output={
                                "content": str(result_content)[:2000] if result_content else "",
                                "is_error": is_error,
                            },
                        )
                        await db.commit()

    except Exception as e:
        logger.exception(f"Claude complete_with_tools error: {e}")
        return ToolExecutionResult(
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
    cited_uuids = await track_citations(
        final_content, loaded_memory_uuids, memory_group_id, db, session_id
    )

    # Log token usage
    from app.services.context_tracker import log_token_usage
    from app.services.events import publish_complete

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

    return ToolExecutionResult(
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
    messages_for_db: list[MessageInput] | None,
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
    project_id: str | None = None,
) -> ToolExecutionResult:
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
            project_id=project_id,
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

                # Store tool_result event and commit incrementally so events
                # survive if the agentic loop is interrupted (e.g. 504 timeout)
                await store_tool_result_event(
                    db,
                    session_id,
                    tool_name=tool_use_id,  # Use tool_use_id as reference
                    tool_output={
                        "content": tool_content[:2000] if tool_content else "",
                        "is_error": is_error,
                    },
                )
                await db.commit()
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
                return ToolExecutionResult(
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
        return ToolExecutionResult(
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
    cited_uuids = await track_citations(
        final_content, loaded_memory_uuids, memory_group_id, db, session_id
    )

    # Log token usage
    from app.services.context_tracker import log_token_usage
    from app.services.events import publish_complete

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

    return ToolExecutionResult(
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
