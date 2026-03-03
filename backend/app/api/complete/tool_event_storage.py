"""Event storage utilities for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.event_storage import (
    store_message_event,
    store_thinking_event as _store_thinking_event,
    store_tool_result_event,
    store_tool_use_event,
)
from app.services.events import publish_message

from .helpers import normalize_content_for_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput


async def store_user_messages(
    db: AsyncSession,
    session_id: str,
    messages_for_db: list[MessageInput] | None,
    agent_id: str | None = None,
) -> None:
    """Store user/system messages before tool execution loop."""
    if not messages_for_db:
        return

    for msg in messages_for_db:
        if msg.role in ("user", "system"):
            await store_message_event(
                db=db,
                session_id=session_id,
                role=msg.role,
                content=normalize_content_for_storage(msg.content),
                agent_id=agent_id,
                agent_name=agent_id,
            )
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            await publish_message(session_id, msg.role, content_str)
    await db.commit()


async def store_tool_use(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_input: Any,
    model_used: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Store tool_use event for observability."""
    await store_tool_use_event(
        db,
        session_id,
        tool_name=tool_name,
        tool_input=tool_input if isinstance(tool_input, dict) else {"value": tool_input},
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_id,
    )


async def store_tool_result(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    content: str,
    is_error: bool = False,
    duration_ms: int | None = None,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> None:
    """Store tool_result event and commit incrementally."""
    tool_output: dict[str, Any] = {
        "content": str(content)[:2000] if content else "",
        "is_error": is_error,
    }
    if tool_use_id:
        tool_output["tool_use_id"] = tool_use_id
    await store_tool_result_event(
        db,
        session_id,
        tool_name=tool_name,
        tool_output=tool_output,
        duration_ms=duration_ms,
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_id,
    )
    await db.commit()


async def store_thinking_event(
    db: AsyncSession,
    session_id: str,
    thinking_content: str,
    tokens: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Store thinking event immediately during the event loop."""
    await _store_thinking_event(
        db=db,
        session_id=session_id,
        thinking_content=thinking_content,
        tokens=tokens,
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_id,
    )


async def store_assistant_response(
    db: AsyncSession,
    session_id: str,
    content: str,
    model: str,
    estimated_tokens: int,
    agent_id: str | None = None,
) -> None:
    """Store assistant response message.

    Note: Thinking events are now stored during the event loop via
    store_thinking_event() for correct (turn, sequence) ordering.
    """
    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=content,
        tokens=estimated_tokens,
        model_used=model,
        agent_id=agent_id,
        agent_name=agent_id,
    )
    await publish_message(session_id, "assistant", content, estimated_tokens)
