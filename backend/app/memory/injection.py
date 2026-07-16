"""Memory context injection.

Moved from ``app.api.complete.memory_handler`` per convergence-map.md C4.
The new pipeline composes this with session_repo + routing in the HTTP
route handler; the adapter remains memory-agnostic.
"""

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
from app.services.memory.context_resilience import (
    CanonicalContextInjectionFailed,
    build_unexpected_context_failure_notice,
    require_successful_context_injection,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _memory_block_len(progressive_context: Any, field_name: str) -> int:
    """Return the size of a progressive-context block, tolerating legacy test doubles."""
    return len(getattr(progressive_context, field_name, []))


async def inject_memory_context(
    messages: list[dict[str, Any]],
    db: AsyncSession | None,
    session_id: str,
    memory_group_id: str | None,
    task_type: str | None = None,
    phase: str | None = None,
    memory_config: dict[str, Any] | None = None,
    current_branch: str | None = None,
    agent_id: str | None = None,
    agent_slug: str | None = None,
    project_id: str | None = None,
    include_memories: bool = True,
    consumer_surface: str = "agent_runtime",
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Inject progressive memory context into messages.

    Returns ``(modified messages, loaded memory UUIDs, facts count)``.
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
            project_id=project_id,
            consumer_profile=consumer_profile,
            consumer_agent_slug=agent_slug,
            consumer_surface=consumer_surface,
            include_prompts=True,
            include_memories=include_memories,
            db=db,
        )
        require_successful_context_injection(progressive_context)
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
            if db is not None:
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
    except CanonicalContextInjectionFailed:
        raise
    except Exception as exc:
        logger.exception("Canonical context injection failed unexpectedly")
        raise CanonicalContextInjectionFailed(
            build_unexpected_context_failure_notice(
                exc,
                operation="complete_internal_context_injection",
                consumer_profile=resolve_memory_consumer_profile(
                    memory_config, surface="runtime"
                ),
                project_id=project_id or scope_id,
            )
        ) from exc

    return messages, loaded_memory_uuids, memory_facts_injected


__all__ = ["inject_memory_context"]
