"""Event storage helpers for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.event_storage import store_message_event, store_thinking_event

from .helpers import normalize_content_for_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


async def save_events(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    assistant_content: str,
    input_tokens: int,
    output_tokens: int,
    model_used: str | None = None,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
    agent_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Save user messages, thinking, and assistant response as events."""
    # Attribute input_tokens to the last user message for stats aggregation
    user_msgs = [msg for msg in user_messages if msg.role in ("user", "system")]
    for i, msg in enumerate(user_msgs):
        is_last = i == len(user_msgs) - 1
        await store_message_event(
            db=db,
            session_id=session_id,
            role=msg.role,
            content=normalize_content_for_storage(msg.content),
            tokens=input_tokens if is_last else None,
            agent_id=agent_id,
            agent_name=agent_id,
        )

    if thinking_content:
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=thinking_content,
            tokens=thinking_tokens,
            model_used=model_used,
            agent_id=agent_id,
            agent_name=agent_id,
        )

    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        tokens=output_tokens,
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_id,
        duration_ms=duration_ms,
    )
    await db.commit()
