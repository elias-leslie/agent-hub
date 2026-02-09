"""Multi-turn execution logic for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message, ProviderError
from app.services.container_manager import ContainerManager
from app.services.event_storage import (
    get_sequencer,
    store_memory_cite_event,
    store_message_event,
    store_thinking_event,
    store_tool_use_event,
)
from app.services.events import publish_message
from app.services.memory import (
    extract_uuid_prefixes,
    parse_memory_group_id,
    resolve_full_uuids,
    track_referenced_batch,
)

from .helpers import is_error_response
from .tool_handlers import AgentProgress

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.response_cache import ResponseCache

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


async def execute_multi_turn(
    adapter: Any,
    messages_dict: list[dict[str, Any]],
    model: str,
    provider: str,
    temperature: float,
    max_turns: int,
    enable_caching: bool,
    cache_ttl: str,
    thinking_level: str | None,
    tools: list[dict[str, Any]] | None,
    enable_programmatic_tools: bool,
    container_id: str | None,
    response_format: dict[str, Any] | None,
    working_dir: str | None,
    db: AsyncSession,
    session_id: str,
    user_messages_for_db: list[MessageInput] | None,
    skip_cache: bool,
    cache: ResponseCache,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    progress_callback: Callable[[AgentProgress], Any] | None,
) -> dict[str, Any]:
    """Execute multi-turn completion loop.

    Returns:
        Dict with execution results including tokens, content, citations, etc.
    """
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
                    result.container.id, result.container.expires_at, session_id
                )

            final_content = result.content
            final_finish_reason = result.finish_reason
            final_result = result

            # Store events for turn 1 (user messages, thinking, assistant response)
            if turn == 1:
                if user_messages_for_db:
                    from .event_helpers import save_events

                    await save_events(
                        db,
                        session_id,
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
                            await publish_message(session_id, msg.role, content_str)
                    await publish_message(session_id, "assistant", result.content, result.output_tokens)

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
                get_sequencer().next_turn(session_id)

                if result.thinking_content:
                    await store_thinking_event(
                        db,
                        session_id,
                        result.thinking_content,
                        tokens=result.thinking_tokens,
                        model_used=model,
                    )

                if result.content:
                    await store_message_event(
                        db,
                        session_id,
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
                    session_id,
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

    # Track all cited UUIDs
    cited_uuids_list = list(all_cited_uuids)
    if cited_uuids_list:
        await track_referenced_batch(cited_uuids_list)
        await store_memory_cite_event(db, session_id, cited_uuids_list)
        logger.info(f"execute_multi_turn: tracked {len(cited_uuids_list)} cited memory rules")

    return {
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_thinking_tokens": total_thinking_tokens,
        "tool_calls_count": tool_calls_count,
        "progress_log": progress_log,
        "cited_uuids_list": cited_uuids_list,
        "final_content": final_content,
        "final_finish_reason": final_finish_reason,
        "final_result": final_result,
        "current_container_id": current_container_id,
        "execution_status": execution_status,
        "execution_error": execution_error,
    }
