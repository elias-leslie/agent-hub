"""Multi-turn execution logic for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message, ProviderError
from app.services.container_manager import ContainerManager

from .context_compaction import maybe_compact_context
from .multi_turn_helpers import (
    TurnLoopConfig,
    build_result,
    handle_provider_error,
    init_execution_state,
    record_timeout_in_health_prober,
)
from .multi_turn_loop import run_turn_loop

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.response_cache import ResponseCache

    from .schemas import MessageInput
    from .tool_handlers import AgentProgress

logger = logging.getLogger(__name__)


def _make_cfg(
    adapter: Any,
    messages_dict: list[dict[str, Any]],
    model: str, provider: str, temperature: float, max_turns: int,
    enable_caching: bool, cache_ttl: str, thinking_level: str | None,
    tools: list[dict[str, Any]] | None, enable_programmatic_tools: bool,
    response_format: dict[str, Any] | None, working_dir: str | None,
    db: Any, session_id: str, user_messages_for_db: Any,
    skip_cache: bool, cache: Any, loaded_memory_uuids: list[str],
    memory_group_id: str | None, progress_callback: Any,
    agent_slug: str | None, per_turn_timeout: float | None,
) -> TurnLoopConfig:
    """Build a TurnLoopConfig from raw execute_multi_turn arguments."""
    return TurnLoopConfig(
        adapter=adapter, model=model, provider=provider, temperature=temperature,
        max_turns=max_turns, enable_caching=enable_caching, cache_ttl=cache_ttl,
        thinking_level=thinking_level, tools=tools,
        enable_programmatic_tools=enable_programmatic_tools,
        response_format=response_format, working_dir=working_dir,
        db=db, session_id=session_id, user_messages_for_db=user_messages_for_db,
        skip_cache=skip_cache, cache=cache, loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id, progress_callback=progress_callback,
        agent_slug=agent_slug, per_turn_timeout=per_turn_timeout,
        messages_dict=messages_dict,
        messages_for_adapter=[Message(role=m["role"], content=m["content"]) for m in messages_dict],
    )


async def _run_with_error_handling(
    cfg: TurnLoopConfig,
    state: dict[str, Any],
    container_manager: ContainerManager,
) -> None:
    """Run the turn loop, recording errors into state on failure."""
    try:
        await run_turn_loop(cfg, state, container_manager)
    except ProviderError as e:
        await handle_provider_error(e, state, cfg.db, cfg.session_id, cfg.model, cfg.agent_slug)
        raise
    except TimeoutError as e:
        record_timeout_in_health_prober(cfg.provider, e)
        state["execution_status"] = "error"
        state["execution_error"] = str(e)
        raise


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
    per_turn_timeout: float | None = None,
) -> dict[str, Any]:
    """Execute multi-turn completion loop.

    Args:
        per_turn_timeout: Max seconds for a single turn (LLM call + tool execution).
            Acts as an inactivity timeout — the total session has no fixed cap.

    Returns:
        Dict with execution results including tokens, content, citations, etc.
    """
    messages_dict, was_compacted = await maybe_compact_context(messages_dict, model)
    if was_compacted:
        logger.info("Context compacted before turn loop (resumed session)")

    cfg = _make_cfg(
        adapter, messages_dict, model, provider, temperature, max_turns,
        enable_caching, cache_ttl, thinking_level, tools, enable_programmatic_tools,
        response_format, working_dir, db, session_id, user_messages_for_db,
        skip_cache, cache, loaded_memory_uuids, memory_group_id,
        progress_callback, agent_slug, per_turn_timeout,
    )
    state = init_execution_state(container_id)
    await _run_with_error_handling(cfg, state, ContainerManager())
    return build_result(state)
