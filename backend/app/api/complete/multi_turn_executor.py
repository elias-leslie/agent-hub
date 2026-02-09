"""Multi-turn execution logic for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message, ProviderError
from app.services.container_manager import ContainerManager

from .finish_reason_handler import handle_finish_reason
from .tool_handlers import AgentProgress
from .turn_processor import (
    create_progress,
    process_first_turn,
    process_subsequent_turn,
    report_progress,
    store_tool_events,
)

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
            progress = create_progress(turn, "running", f"Turn {turn}: sending to {provider}")
            progress_log.append(progress)
            await report_progress(progress, progress_callback)

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

            # Process turn and track citations
            if turn == 1:
                cited_uuids = await process_first_turn(
                    db,
                    session_id,
                    result,
                    model,
                    user_messages_for_db,
                    messages_dict,
                    temperature,
                    skip_cache,
                    cache,
                    loaded_memory_uuids,
                    memory_group_id,
                )
            else:
                cited_uuids = await process_subsequent_turn(
                    db, session_id, result, model, loaded_memory_uuids, memory_group_id
                )

            all_cited_uuids.update(cited_uuids)

            # Store tool use events
            await store_tool_events(db, session_id, result.tool_calls)
            await db.commit()

            # Handle finish reason
            should_break, execution_status, execution_error = await handle_finish_reason(
                result.finish_reason,
                turn,
                max_turns,
                result,
                messages_for_adapter,
                progress_log,
                progress_callback,
            )
            if should_break:
                break

    except ProviderError as e:
        execution_status = "error"
        execution_error = str(e)
        logger.exception(f"Provider error during multi-turn execution: {e}")

    # Return execution results
    cited_uuids_list = list(all_cited_uuids)
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
