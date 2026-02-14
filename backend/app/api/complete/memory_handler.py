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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
    loaded_memory_uuids: list[str] = []
    memory_facts_injected = 0

    try:
        messages, progressive_context = await inject_progressive_context(
            messages=messages,
            scope=scope,
            scope_id=scope_id,
            task_type=task_type,
            phase=phase,
            memory_config=memory_config,
            current_branch=current_branch,
        )
        memory_facts_injected = (
            len(progressive_context.mandates)
            + len(progressive_context.guardrails)
            + len(progressive_context.reference)
        )
        loaded_memory_uuids = progressive_context.get_loaded_uuids()

        if memory_facts_injected > 0:
            logger.info(f"inject_memory_context: injected {memory_facts_injected} memory facts")
            await track_loaded_batch(loaded_memory_uuids)
            await store_memory_inject_event(
                db, session_id, loaded_memory_uuids, memory_facts_injected,
                agent_id=agent_id,
            )
    except Exception as e:
        logger.warning(f"Memory injection failed (continuing without): {e}")

    return messages, loaded_memory_uuids, memory_facts_injected
