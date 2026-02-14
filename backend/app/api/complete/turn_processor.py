"""Turn execution logic for multi-turn completion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.event_storage import (
    get_sequencer,
    store_message_event,
    store_thinking_event,
    store_tool_use_event,
)
from app.services.events import publish_message

from .citation_tracker import track_citations
from .event_helpers import save_events
from .helpers import is_error_response
from .tool_handlers import AgentProgress

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.response_cache import ResponseCache

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


async def process_first_turn(
    db: AsyncSession,
    session_id: str,
    result: Any,
    model: str,
    user_messages_for_db: list[MessageInput] | None,
    messages_dict: list[dict[str, Any]],
    temperature: float,
    skip_cache: bool,
    cache: ResponseCache,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    agent_slug: str | None = None,
    duration_ms: int | None = None,
) -> list[str]:
    """Process first turn: save events, cache response, track citations.

    Returns:
        List of cited UUIDs
    """
    cited_uuids: list[str] = []

    if user_messages_for_db:
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

    # Cache first turn response if successful
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

    # Track citations
    if result.content:
        cited_uuids = await track_citations(
            result.content, loaded_memory_uuids, memory_group_id, db, session_id
        )

    return cited_uuids


async def process_subsequent_turn(
    db: AsyncSession,
    session_id: str,
    result: Any,
    model: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    agent_slug: str | None = None,
    duration_ms: int | None = None,
) -> list[str]:
    """Process subsequent turns: advance sequencer, store events, track citations.

    Returns:
        List of cited UUIDs
    """
    get_sequencer().next_turn(session_id)

    if result.thinking_content:
        await store_thinking_event(
            db, session_id, result.thinking_content, tokens=result.thinking_tokens, model_used=model,
            agent_id=agent_slug, agent_name=agent_slug,
        )

    if result.content:
        await store_message_event(
            db, session_id, role="assistant", content=result.content, tokens=result.output_tokens, model_used=model,
            agent_id=agent_slug, agent_name=agent_slug, duration_ms=duration_ms,
        )

    # Track citations
    cited_uuids: list[str] = []
    if result.content:
        cited_uuids = await track_citations(
            result.content, loaded_memory_uuids, memory_group_id, db, session_id
        )

    return cited_uuids


async def store_tool_events(
    db: AsyncSession,
    session_id: str,
    tool_calls: list[Any] | None,
    model_used: str | None = None,
    agent_slug: str | None = None,
) -> None:
    """Store tool use events."""
    for tc in tool_calls or []:
        await store_tool_use_event(
            db,
            session_id,
            tool_name=tc.name,
            tool_input=tc.input if isinstance(tc.input, dict) else {"value": tc.input},
            model_used=model_used,
            agent_id=agent_slug,
            agent_name=agent_slug,
        )


def create_progress(
    turn: int, status: str, message: str, tool_calls: list[dict[str, Any]] | None = None
) -> AgentProgress:
    """Create progress object."""
    return AgentProgress(turn=turn, status=status, message=message, tool_calls=tool_calls)


async def report_progress(
    progress: AgentProgress, callback: Callable[[AgentProgress], Any] | None
) -> None:
    """Report progress if callback is provided."""
    if callback:
        await callback(progress)
