"""Response cache handling for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete
from app.services.token_counter import estimate_cost

from .event_helpers import save_events
from .schemas import MessageInput

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession
    from app.services.response_cache import CachedResponse

logger = logging.getLogger(__name__)


async def handle_cached_response(
    cached: CachedResponse,
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    model: str,
    user_messages_for_db: list[MessageInput] | None,
    loaded_memory_uuids: list[str],
    is_new_session: bool,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Handle returning a cached completion response.

    Args:
        cached: Cached response data
        db: Database session
        session: DB session object
        session_id: Session ID
        model: Model identifier
        user_messages_for_db: Original user messages to save
        loaded_memory_uuids: Memory UUIDs that were loaded
        is_new_session: Whether this is a new session

    Returns:
        Dict with cache response data (content, tokens, etc.)
    """
    logger.info(f"handle_cached_response: returning cached response for {model}")

    if user_messages_for_db:
        await save_events(
            db,
            session_id,
            user_messages_for_db,
            cached.content,
            cached.input_tokens,
            cached.output_tokens,
            model_used=model,
            agent_id=agent_id,
        )

    cost = estimate_cost(cached.input_tokens, cached.output_tokens, model)
    await log_token_usage(
        db,
        session_id,
        model,
        cached.input_tokens,
        cached.output_tokens,
        cost.total_cost_usd,
    )
    await publish_complete(session_id, cached.input_tokens, cached.output_tokens, cost.total_cost_usd)

    # Mark new sessions as completed (cached single-turn completions are done)
    if is_new_session:
        session.status = "completed"

    await db.commit()

    return {
        "content": cached.content,
        "model": cached.model,
        "provider": cached.provider,
        "input_tokens": cached.input_tokens,
        "output_tokens": cached.output_tokens,
        "finish_reason": cached.finish_reason,
        "session_id": session_id,
        "memory_uuids": loaded_memory_uuids,
        "cited_uuids": [],
        "from_cache": True,
    }
