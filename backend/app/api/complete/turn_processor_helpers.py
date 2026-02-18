"""Private helper functions for turn_processor.py."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.events import publish_message

from .event_helpers import save_events
from .helpers import is_error_response

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.response_cache import ResponseCache

    from .schemas import MessageInput


async def _save_and_publish_user_events(
    db: AsyncSession,
    session_id: str,
    user_messages_for_db: list[MessageInput],
    result: Any,
    model: str,
    agent_slug: str | None,
    duration_ms: int | None,
) -> None:
    """Save events to DB and publish user/assistant messages."""
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
        agent_id=agent_slug,
        duration_ms=duration_ms,
    )
    for msg in user_messages_for_db:
        if msg.role in ("user", "system"):
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            await publish_message(session_id, msg.role, content_str)
    await publish_message(session_id, "assistant", result.content, result.output_tokens)


async def _cache_first_turn_response(
    cache: ResponseCache,
    model: str,
    messages_dict: list[dict[str, Any]],
    temperature: float,
    result: Any,
    skip_cache: bool,
) -> None:
    """Cache the first-turn response if conditions are met."""
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
