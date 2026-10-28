"""Event storage helpers for completion API."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.services.event_storage import (
    TOOL_RESULT_SUMMARY_CHARS,
    store_message_event,
    store_thinking_event,
    store_tool_result_event,
    store_tool_use_event,
)

from .helpers import normalize_content_for_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import MessageInput

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnTraceStep:
    """One thing the model did before it answered: thought, called a tool, or got a tool's result."""

    kind: Literal["thinking", "tool_use", "tool_result"]
    text: str = ""
    tool_name: str | None = None
    call_id: str | None = None
    tool_input: dict[str, object] | None = None
    is_error: bool = False
    duration_ms: int | None = None


async def _save_turn_trace(
    db: AsyncSession,
    session_id: str,
    trace: Sequence[TurnTraceStep],
    thinking_tokens: int | None,
    model_used: str | None,
    agent_id: str | None,
    source_metadata: dict[str, object] | None,
) -> None:
    """Store the turn's thinking and tool calls in order, as the events a reopened chat is built from."""
    last_thinking = max((i for i, step in enumerate(trace) if step.kind == "thinking"), default=-1)
    for index, step in enumerate(trace):
        common = {
            "model_used": model_used,
            "agent_id": agent_id,
            "agent_name": agent_id,
            **(source_metadata or {}),
        }
        if step.kind == "thinking":
            await store_thinking_event(
                db=db,
                session_id=session_id,
                thinking_content=step.text,
                tokens=thinking_tokens if index == last_thinking else None,
                **common,
            )
        elif step.kind == "tool_use":
            await store_tool_use_event(
                db, session_id, step.tool_name or "unknown", step.tool_input or {}, call_id=step.call_id, **common
            )
        else:
            text = step.text
            if len(text) > TOOL_RESULT_SUMMARY_CHARS:
                text = f"{text[:TOOL_RESULT_SUMMARY_CHARS]}…"
            await store_tool_result_event(
                db,
                session_id,
                step.tool_name or "unknown",
                {"content": text, "is_error": step.is_error},
                duration_ms=step.duration_ms,
                call_id=step.call_id,
                **common,
            )


async def save_user_message_events(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    input_tokens: int | None,
    agent_id: str | None,
    source_metadata: dict[str, object] | None = None,
) -> None:
    """Store only the last user/system message (prior turns already persisted)."""
    user_msgs = [msg for msg in user_messages if msg.role in ("user", "system")]
    if not user_msgs:
        return
    msg = user_msgs[-1]
    await store_message_event(
        db=db,
        session_id=session_id,
        role=msg.role,
        content=normalize_content_for_storage(msg.content),
        tokens=input_tokens,
        agent_id=agent_id,
        agent_name=agent_id,
        **(source_metadata or {}),
    )


async def _save_thinking_event(
    db: AsyncSession,
    session_id: str,
    thinking_content: str | None,
    thinking_tokens: int | None,
    model_used: str | None,
    agent_id: str | None,
    source_metadata: dict[str, object] | None = None,
) -> None:
    """Store the thinking event when thinking content is present."""
    if thinking_content:
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=thinking_content,
            tokens=thinking_tokens,
            model_used=model_used,
            agent_id=agent_id,
            agent_name=agent_id,
            **(source_metadata or {}),
        )


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
    source_metadata: dict[str, object] | None = None,
    commit: bool = True,
    usage: dict[str, object] | None = None,
    trace: Sequence[TurnTraceStep] = (),
) -> None:
    """Save user messages, thinking, and assistant response as events.

    ``usage`` is stored on the assistant event (provider outcome payload). ``trace`` is the turn's streamed
    thinking and tool calls; they are stored between the prompt and the answer.
    """
    await save_user_message_events(db, session_id, user_messages, input_tokens, agent_id, source_metadata)
    await _save_thinking_event(
        db,
        session_id,
        thinking_content,
        thinking_tokens,
        model_used,
        agent_id,
        source_metadata,
    )
    await _save_turn_trace(db, session_id, trace, thinking_tokens, model_used, agent_id, source_metadata)
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
        usage=usage,
        **(source_metadata or {}),
    )
    if commit:
        await db.commit()
