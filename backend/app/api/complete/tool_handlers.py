"""Tool execution handlers for Claude and Gemini providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession

from .tool_event_storage import (
    store_assistant_response,
    store_tool_result,
    store_tool_use,
    store_user_messages,
)
from .tool_models import AgentProgress, ToolExecutionResult

__all__ = ["AgentProgress", "ToolExecutionResult", "_complete_with_claude_tools", "_complete_with_gemini_tools"]
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result, finalize_result

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


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
    """Execute completion using Claude's complete_with_tools() for full observability."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock, UserMessage

    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_count = 0
    turn = 0
    tracker = ProgressTracker(progress_callback)

    # Store user messages first
    await store_user_messages(db, session_id, messages_for_db)

    # Map permission_config to Claude SDK params
    yolo_mode = True
    write_enabled = True
    if permission_config and permission_config.get("mode") == "granular":
        yolo_mode = False
        allow_list = set(permission_config.get("allow_list", []))
        deny_list = set(permission_config.get("deny_list", []))
        write_tools = {"write_file", "edit_file", "delete_file", "create_directory"}
        write_enabled = bool(allow_list & write_tools) and not bool(deny_list & write_tools)

    try:
        async for msg, _sess_id in adapter.complete_with_tools(
            messages=messages_for_adapter,
            model=model,
            tools=tools or [],
            working_dir=working_dir,
            write_enabled=write_enabled,
            yolo_mode=yolo_mode,
        ):
            msg_type = type(msg).__name__

            # Extract thinking blocks
            if msg_type == "ThinkingBlock" or (hasattr(msg, "type") and msg.type == "thinking"):
                thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
                if thinking_text:
                    thinking_parts.append(thinking_text)

            # Track tool use
            if msg_type == "ToolUseBlock" or (hasattr(msg, "type") and msg.type == "tool_use"):
                tool_calls_count += 1
                tool_name = getattr(msg, "name", "unknown")
                tool_input = getattr(msg, "input", {})
                await store_tool_use(db, session_id, tool_name, tool_input)
                await tracker.report_tool_use(turn, tool_name, tool_input)

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
                    # Check for ToolUseBlock inside AssistantMessage
                    if block_type == "ToolUseBlock" or getattr(block, "type", "") == "tool_use":
                        tool_calls_count += 1
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        await store_tool_use(db, session_id, tool_name, tool_input)
                        await tracker.report_tool_use(turn, tool_name, tool_input)

            # Handle UserMessage (contains tool results from SDK)
            if isinstance(msg, UserMessage) and hasattr(msg, "content"):
                for block in msg.content:  # type: ignore
                    block_type = type(block).__name__
                    if block_type == "ToolResultBlock":
                        result_content = getattr(block, "content", "")
                        is_error = getattr(block, "is_error", False)
                        tool_use_id = getattr(block, "tool_use_id", "")
                        await store_tool_result(db, session_id, tool_use_id, result_content, is_error)

    except Exception as e:
        logger.exception(f"Claude complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    # Finalize result
    final_content = "".join(content_parts)
    thinking_content = "\n".join(thinking_parts) if thinking_parts else None
    thinking_tokens = len(thinking_content) // 4 if thinking_content else None
    estimated_tokens = len(final_content) // 4

    await store_assistant_response(
        db, session_id, final_content, model, estimated_tokens, thinking_content, thinking_tokens
    )

    await tracker.report_complete(turn or 1, tool_calls_count)

    return await finalize_result(
        db=db,
        session=session,
        session_id=session_id,
        is_new_session=is_new_session,
        model=model,
        provider=provider,
        content=final_content,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turn=turn or 1,
        tool_calls_count=tool_calls_count,
        progress_log=tracker.log,
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
    """Execute completion using Gemini's complete_with_tools() for full observability."""
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    content_parts: list[str] = []
    tool_calls_count = 0
    turn = 0
    tracker = ProgressTracker(progress_callback)

    # Store user messages first
    await store_user_messages(db, session_id, messages_for_db)

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

            # Process assistant messages
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
                            await store_tool_use(db, session_id, tool_name, tool_input)
                            await tracker.report_tool_use(turn, tool_name, tool_input)

            # Process tool_result events
            elif event_type == "tool_result":
                tool_content = getattr(event, "content", "")
                tool_use_id = getattr(event, "tool_use_id", "")
                is_error = getattr(event, "is_error", False)
                await store_tool_result(db, session_id, tool_use_id, tool_content, is_error)
                turn += 1

            # Process result event
            elif event_type == "result":
                result_text = getattr(event, "result", "")
                if result_text and result_text not in "".join(content_parts):
                    content_parts.append(result_text)

            # Process error event
            elif event_type == "error":
                error_msg = getattr(event, "error", "Unknown error")
                logger.error(f"Gemini tool execution error: {error_msg}")
                return build_error_result(Exception(error_msg), model, provider, session_id, loaded_memory_uuids)

        await db.commit()

    except Exception as e:
        logger.exception(f"Gemini complete_with_tools error: {e}")
        return build_error_result(e, model, provider, session_id, loaded_memory_uuids)

    # Finalize result
    final_content = "".join(content_parts)
    estimated_tokens = len(final_content) // 4

    await store_assistant_response(db, session_id, final_content, model, estimated_tokens)
    await tracker.report_complete(turn or 1, tool_calls_count)

    return await finalize_result(
        db=db,
        session=session,
        session_id=session_id,
        is_new_session=is_new_session,
        model=model,
        provider=provider,
        content=final_content,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        turn=turn or 1,
        tool_calls_count=tool_calls_count,
        progress_log=tracker.log,
    )
