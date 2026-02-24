"""Multi-turn execution logic for completion API."""

from __future__ import annotations

import logging
import time
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


def _init_execution_state(container_id: str | None) -> dict[str, Any]:
    """Initialize mutable state for a multi-turn execution run."""
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_thinking_tokens": 0,
        "tool_calls_count": 0,
        "progress_log": [],
        "all_cited_uuids": set(),
        "final_content": "",
        "final_finish_reason": None,
        "final_result": None,
        "current_container_id": container_id,
        "execution_status": "success",
        "execution_error": None,
    }


async def _run_adapter_turn(
    adapter: Any,
    messages_for_adapter: list[Message],
    model: str,
    temperature: float,
    enable_caching: bool,
    cache_ttl: str,
    thinking_level: str | None,
    tools: list[dict[str, Any]] | None,
    enable_programmatic_tools: bool,
    current_container_id: str | None,
    response_format: dict[str, Any] | None,
    working_dir: str | None,
    turn: int,
) -> tuple[Any, int]:
    """Call the adapter for one turn and return (result, duration_ms)."""
    turn_start = time.monotonic()
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
    turn_duration_ms = int((time.monotonic() - turn_start) * 1000)
    return result, turn_duration_ms


async def _persist_turn_citations(
    result: Any,
    turn: int,
    db: Any,
    session_id: str,
    model: str,
    user_messages_for_db: list[MessageInput] | None,
    messages_dict: list[dict[str, Any]],
    temperature: float,
    skip_cache: bool,
    cache: Any,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    agent_slug: str | None,
    turn_duration_ms: int,
) -> list[str]:
    """Persist turn records and return cited UUIDs."""
    if turn == 1:
        return await process_first_turn(
            db, session_id, result, model, user_messages_for_db,
            messages_dict, temperature, skip_cache, cache,
            loaded_memory_uuids, memory_group_id,
            agent_slug=agent_slug, duration_ms=turn_duration_ms,
        )
    return await process_subsequent_turn(
        db, session_id, result, model, loaded_memory_uuids, memory_group_id,
        agent_slug=agent_slug, duration_ms=turn_duration_ms,
    )


async def _process_turn_result(
    result: Any,
    turn: int,
    state: dict[str, Any],
    container_manager: ContainerManager,
    db: Any,
    session_id: str,
    model: str,
    user_messages_for_db: list[MessageInput] | None,
    messages_dict: list[dict[str, Any]],
    temperature: float,
    skip_cache: bool,
    cache: Any,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    agent_slug: str | None,
    turn_duration_ms: int,
) -> None:
    """Update execution state from one turn's result and persist DB records."""
    state["total_input_tokens"] += result.input_tokens
    state["total_output_tokens"] += result.output_tokens
    if result.thinking_tokens:
        state["total_thinking_tokens"] += result.thinking_tokens

    if result.container:
        state["current_container_id"] = result.container.id
        container_manager.register(result.container.id, result.container.expires_at, session_id)

    state["final_content"] = result.content
    state["final_finish_reason"] = result.finish_reason
    state["final_result"] = result

    cited_uuids = await _persist_turn_citations(
        result, turn, db, session_id, model, user_messages_for_db,
        messages_dict, temperature, skip_cache, cache,
        loaded_memory_uuids, memory_group_id, agent_slug, turn_duration_ms,
    )
    state["all_cited_uuids"].update(cited_uuids)

    await store_tool_events(db, session_id, result.tool_calls, model_used=model, agent_slug=agent_slug)
    await db.commit()


async def _handle_provider_error(
    e: ProviderError,
    state: dict[str, Any],
    db: Any,
    session_id: str,
    model: str,
    agent_slug: str | None,
) -> None:
    """Record a ProviderError into state and attempt to persist an error event."""
    state["execution_status"] = "error"
    state["execution_error"] = str(e)
    logger.exception(f"Provider error during multi-turn execution: {e}")
    try:
        from app.services.event_storage import store_error_event

        await store_error_event(
            db, session_id, "ProviderError", str(e),
            agent_id=agent_slug, model_used=model,
        )
        await db.commit()
    except Exception:
        logger.debug("Failed to store error event", exc_info=True)


def _build_result(state: dict[str, Any]) -> dict[str, Any]:
    """Build the final return dict from execution state."""
    return {
        "total_input_tokens": state["total_input_tokens"],
        "total_output_tokens": state["total_output_tokens"],
        "total_thinking_tokens": state["total_thinking_tokens"],
        "tool_calls_count": state["tool_calls_count"],
        "progress_log": state["progress_log"],
        "cited_uuids_list": list(state["all_cited_uuids"]),
        "final_content": state["final_content"],
        "final_finish_reason": state["final_finish_reason"],
        "final_result": state["final_result"],
        "current_container_id": state["current_container_id"],
        "execution_status": state["execution_status"],
        "execution_error": state["execution_error"],
    }


async def _execute_single_turn(
    turn: int,
    adapter: Any,
    messages_for_adapter: list[Message],
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
    response_format: dict[str, Any] | None,
    working_dir: str | None,
    db: Any,
    session_id: str,
    user_messages_for_db: list[MessageInput] | None,
    skip_cache: bool,
    cache: Any,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    progress_callback: Callable[[AgentProgress], Any] | None,
    agent_slug: str | None,
    state: dict[str, Any],
    container_manager: ContainerManager,
    auto_tier: bool = False,
) -> bool:
    """Execute one turn; return True if the loop should stop."""
    # Auto-tier: re-evaluate model complexity for turns after the first
    if auto_tier and turn > 1 and messages_for_adapter:
        latest_content = messages_for_adapter[-1].content if messages_for_adapter else ""
        if latest_content:
            from app.services.model_selector import select_model_for_request

            selected = select_model_for_request(latest_content, agent_slug=agent_slug)
            if selected.id != model:
                logger.info(f"Auto-tier: {model} → {selected.id} (turn {turn})")
                model = selected.id

    # Per-turn compaction: prune context if it grew too large during execution
    if turn > 1:
        from .context_compaction import maybe_compact_context

        messages_dict, was_compacted = await maybe_compact_context(messages_dict, model)
        if was_compacted:
            messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages_dict]
            logger.info(f"Context compacted at turn {turn}")

    progress = create_progress(turn, "running", f"Turn {turn}: sending to {provider}")
    state["progress_log"].append(progress)
    await report_progress(progress, progress_callback)

    result, turn_duration_ms = await _run_adapter_turn(
        adapter, messages_for_adapter, model, temperature,
        enable_caching, cache_ttl, thinking_level, tools,
        enable_programmatic_tools, state["current_container_id"],
        response_format, working_dir, turn,
    )
    await _process_turn_result(
        result, turn, state, container_manager, db, session_id,
        model, user_messages_for_db, messages_dict, temperature,
        skip_cache, cache, loaded_memory_uuids, memory_group_id,
        agent_slug, turn_duration_ms,
    )
    should_break, state["execution_status"], state["execution_error"] = await handle_finish_reason(
        result.finish_reason, turn, max_turns, result,
        messages_for_adapter, state["progress_log"], progress_callback,
    )
    return should_break


async def _run_turn_loop(
    adapter: Any,
    messages_for_adapter: list[Message],
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
    response_format: dict[str, Any] | None,
    working_dir: str | None,
    db: Any,
    session_id: str,
    user_messages_for_db: list[MessageInput] | None,
    skip_cache: bool,
    cache: Any,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    progress_callback: Callable[[AgentProgress], Any] | None,
    agent_slug: str | None,
    state: dict[str, Any],
    container_manager: ContainerManager,
    auto_tier: bool = False,
) -> None:
    """Run the multi-turn loop, updating state in place."""
    for turn in range(1, max_turns + 1):
        should_break = await _execute_single_turn(
            turn, adapter, messages_for_adapter, messages_dict, model,
            provider, temperature, max_turns, enable_caching, cache_ttl,
            thinking_level, tools, enable_programmatic_tools, response_format,
            working_dir, db, session_id, user_messages_for_db, skip_cache,
            cache, loaded_memory_uuids, memory_group_id, progress_callback,
            agent_slug, state, container_manager, auto_tier=auto_tier,
        )
        if should_break:
            break


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
    agent_slug: str | None = None,
    auto_tier: bool = False,
) -> dict[str, Any]:
    """Execute multi-turn completion loop.

    Args:
        auto_tier: When True, re-evaluate model complexity per-turn and
            switch models dynamically within the same provider family.

    Returns:
        Dict with execution results including tokens, content, citations, etc.
    """
    # Pre-loop compaction for resumed sessions with large existing context
    from .context_compaction import maybe_compact_context

    messages_dict, was_compacted = await maybe_compact_context(messages_dict, model)
    if was_compacted:
        logger.info("Context compacted before turn loop (resumed session)")

    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages_dict]
    state = _init_execution_state(container_id)
    container_manager = ContainerManager()

    try:
        await _run_turn_loop(
            adapter, messages_for_adapter, messages_dict, model, provider,
            temperature, max_turns, enable_caching, cache_ttl, thinking_level,
            tools, enable_programmatic_tools, response_format, working_dir,
            db, session_id, user_messages_for_db, skip_cache, cache,
            loaded_memory_uuids, memory_group_id, progress_callback,
            agent_slug, state, container_manager, auto_tier=auto_tier,
        )
    except ProviderError as e:
        await _handle_provider_error(e, state, db, session_id, model, agent_slug)
        raise

    return _build_result(state)
