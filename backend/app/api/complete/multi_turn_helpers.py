"""State management and persistence helpers for multi-turn execution."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import ProviderError
from app.services.container_manager import ContainerManager
from app.services.session_health import health_detail_for_error, update_session_health

from .turn_processor import (
    process_first_turn,
    process_subsequent_turn,
    store_tool_events,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.adapters.base import Message

    from .schemas import MessageInput
    from .tool_handlers import AgentProgress

logger = logging.getLogger(__name__)


@dataclass
class TurnLoopConfig:
    """Config shared across all turns in a multi-turn loop.

    Set max_turns (user's limit, e.g. 200).  Derived checkpoint fields
    are computed automatically in __post_init__:
        soft_limit        = max_turns // 2          (checkpoint start)
        checkpoint_interval = soft_limit // 4       (~4 checkpoints)
        wrapup_turn       = max_turns               (wrap-up message)
        hard_cap          = max_turns + grace_turns  (absolute stop)
    """

    adapter: Any
    model: str
    provider: str
    temperature: float
    max_turns: int
    enable_caching: bool
    cache_ttl: str
    thinking_level: str | None
    tools: list[dict[str, Any]] | None
    enable_programmatic_tools: bool
    response_format: dict[str, Any] | None
    working_dir: str | None
    db: Any
    session_id: str
    user_messages_for_db: list[MessageInput] | None
    skip_cache: bool
    cache: Any
    loaded_memory_uuids: list[str]
    memory_group_id: str | None
    progress_callback: Callable[[AgentProgress], Any] | None
    agent_slug: str | None
    task_type: str | None = None
    messages_dict: list[dict[str, Any]] = field(default_factory=list)
    messages_for_adapter: list[Message] = field(default_factory=list)

    # Derived checkpoint fields — computed in __post_init__
    soft_limit: int = field(init=False, default=0)
    checkpoint_interval: int = field(init=False, default=1)
    wrapup_turn: int = field(init=False, default=0)
    hard_cap: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.max_turns <= 4:
            # Small turn counts: no checkpoints, no grace
            self.soft_limit = 0
            self.checkpoint_interval = 1
            self.wrapup_turn = 0
            self.hard_cap = self.max_turns
        else:
            self.soft_limit = self.max_turns // 2
            self.checkpoint_interval = max(self.soft_limit // 4, 1)
            grace = min(math.ceil(self.max_turns * 0.1), 25)
            self.wrapup_turn = self.max_turns
            self.hard_cap = self.max_turns + grace


def init_execution_state(container_id: str | None) -> dict[str, Any]:
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
        "closeout_audit_used": False,
    }


async def persist_turn_citations(
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


async def process_turn_result(
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

    cited_uuids = await persist_turn_citations(
        result, turn, db, session_id, model, user_messages_for_db,
        messages_dict, temperature, skip_cache, cache,
        loaded_memory_uuids, memory_group_id, agent_slug, turn_duration_ms,
    )
    state["all_cited_uuids"].update(cited_uuids)

    await store_tool_events(db, session_id, result.tool_calls, model_used=model, agent_slug=agent_slug)
    await db.commit()


async def handle_provider_error(
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
        await update_session_health(
            db,
            session_id,
            health_detail_for_error(e),
            commit=True,
        )
        from app.services.event_storage import store_error_event

        await store_error_event(
            db, session_id, "ProviderError", str(e),
            agent_id=agent_slug, model_used=model,
        )
        await db.commit()
    except Exception:
        logger.debug("Failed to store error event", exc_info=True)


def build_result(state: dict[str, Any]) -> dict[str, Any]:
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


def record_timeout_in_health_prober(provider: str, e: TimeoutError) -> None:
    """Record a timeout as a health prober failure for the given provider."""
    try:
        from app.services.health_prober import record_provider_failure

        record_provider_failure(provider, f"Timeout: {e}")
        logger.warning("Timeout recorded as health prober failure for %s", provider)
    except Exception:
        logger.debug("Failed to record timeout in health prober", exc_info=True)
