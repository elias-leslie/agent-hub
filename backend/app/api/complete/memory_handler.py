"""Memory context injection for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.event_storage import store_memory_inject_event
from app.services.memory import (
    inject_progressive_context,
    parse_memory_group_id,
    track_loaded_batch,
)
from app.services.memory.context_builder_settings import resolve_memory_consumer_profile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _memory_block_len(progressive_context: Any, field_name: str) -> int:
    """Return the size of a progressive-context block, tolerating legacy test doubles."""
    return len(getattr(progressive_context, field_name, []))


async def inject_memory_context(
    messages: list[dict[str, Any]],
    db: AsyncSession,
    session_id: str,
    memory_group_id: str | None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    agent_id: str | None = None,
    agent_slug: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Inject progressive memory context into messages.

    Args:
        messages: Conversation messages
        db: Database session
        session_id: Session ID
        memory_group_id: Memory group for isolation
        task_type: Optional task type for triggered reference injection
        phase: Optional phase for phase-triggered reference injection
        memory_config: Optional memory configuration
        current_branch: Optional git branch for continuity scoping

    Returns:
        Tuple of (modified messages, loaded memory UUIDs, facts count)
    """
    scope, scope_id = parse_memory_group_id(memory_group_id)
    logger.info(
        "inject_memory_context: memory_group=%s -> scope=%s scope_id=%s session=%s",
        memory_group_id, scope, scope_id, session_id,
    )
    loaded_memory_uuids: list[str] = []
    memory_facts_injected = 0

    try:
        consumer_profile = resolve_memory_consumer_profile(memory_config, surface="runtime")
        messages, progressive_context = await inject_progressive_context(
            messages=messages,
            scope=scope,
            scope_id=scope_id,
            task_type=task_type,
            phase=phase,
            memory_config=memory_config,
            current_branch=current_branch,
            session_id=session_id,
            consumer_profile=consumer_profile,
            consumer_agent_slug=agent_slug,
        )
        memory_facts_injected = (
            _memory_block_len(progressive_context, "mandates")
            + _memory_block_len(progressive_context, "guardrails")
            + _memory_block_len(progressive_context, "reference_index")
            + _memory_block_len(progressive_context, "reference")
        )
        loaded_memory_uuids = progressive_context.get_loaded_uuids()

        if memory_facts_injected > 0:
            logger.info(f"inject_memory_context: injected {memory_facts_injected} memory facts")
            await track_loaded_batch(loaded_memory_uuids)
            memory_debug = dict(getattr(progressive_context, "debug_info", {}))
            await store_memory_inject_event(
                db, session_id, loaded_memory_uuids, memory_facts_injected,
                reference_selected_uuids=list(
                    memory_debug.get("reference_selected_uuids", [])
                ),
                reference_index_uuids=list(
                    memory_debug.get("reference_index_uuids", [])
                ),
                memory_debug=memory_debug,
                agent_id=agent_id,
            )
    except Exception as e:
        logger.warning(f"Memory injection failed (continuing without): {e}")

    return messages, loaded_memory_uuids, memory_facts_injected
