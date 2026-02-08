"""Event storage service for persisting session events to database."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent, SessionEventType

logger = logging.getLogger(__name__)


class EventSequencer:
    """Track turn and sequence numbers for a session."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, int]] = {}

    def get_turn_sequence(self, session_id: str) -> tuple[int, int]:
        """Get current turn and sequence, auto-incrementing sequence."""
        if session_id not in self._sessions:
            self._sessions[session_id] = {"turn": 1, "sequence": 0}
        state = self._sessions[session_id]
        state["sequence"] += 1
        return state["turn"], state["sequence"]

    def next_turn(self, session_id: str) -> int:
        """Advance to next turn, reset sequence."""
        if session_id not in self._sessions:
            self._sessions[session_id] = {"turn": 1, "sequence": 0}
        else:
            self._sessions[session_id]["turn"] += 1
            self._sessions[session_id]["sequence"] = 0
        return self._sessions[session_id]["turn"]

    def set_turn(self, session_id: str, turn: int, min_sequence: int = 0) -> None:
        """Set turn number (for resuming sessions).

        Only advances forward — never decreases turn or sequence to avoid
        collisions with already-stored events.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = {"turn": turn, "sequence": min_sequence}
        else:
            current = self._sessions[session_id]
            if turn > current["turn"]:
                self._sessions[session_id] = {"turn": turn, "sequence": min_sequence}
            elif turn == current["turn"] and min_sequence > current["sequence"]:
                current["sequence"] = min_sequence


_sequencer: EventSequencer | None = None


def get_sequencer() -> EventSequencer:
    """Get global event sequencer instance."""
    global _sequencer
    if _sequencer is None:
        _sequencer = EventSequencer()
    return _sequencer


async def store_event(
    db: AsyncSession,
    session_id: str,
    event_type: str,
    turn: int | None = None,
    sequence: int | None = None,
    role: str | None = None,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: dict[str, Any] | None = None,
    tokens: int | None = None,
    duration_ms: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> SessionEvent:
    """Store a single event to the database.

    If turn/sequence not provided, auto-generates from sequencer.
    """
    sequencer = get_sequencer()
    if turn is None or sequence is None:
        turn, sequence = sequencer.get_turn_sequence(session_id)

    event = SessionEvent(
        session_id=session_id,
        turn=turn,
        sequence=sequence,
        event_type=event_type,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        tokens=tokens,
        duration_ms=duration_ms,
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    db.add(event)
    return event


async def store_message_event(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    tokens: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> SessionEvent:
    """Store a message event (user, assistant, or system)."""
    event_type_map = {
        "user": SessionEventType.USER_MESSAGE,
        "assistant": SessionEventType.ASSISTANT_MESSAGE,
        "system": SessionEventType.SYSTEM_MESSAGE,
    }
    event_type = event_type_map.get(role, SessionEventType.USER_MESSAGE)

    return await store_event(
        db=db,
        session_id=session_id,
        event_type=event_type,
        role=role,
        content=content,
        tokens=tokens,
        model_used=model_used,
        agent_id=agent_id,
        agent_name=agent_name,
    )


async def store_thinking_event(
    db: AsyncSession,
    session_id: str,
    thinking_content: str,
    tokens: int | None = None,
    model_used: str | None = None,
) -> SessionEvent:
    """Store a thinking/reasoning event."""
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.THINKING,
        content=thinking_content,
        tokens=tokens,
        model_used=model_used,
    )


async def store_tool_use_event(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    duration_ms: int | None = None,
) -> SessionEvent:
    """Store a tool use event."""
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.TOOL_USE,
        tool_name=tool_name,
        tool_input=tool_input,
        duration_ms=duration_ms,
    )


async def store_tool_result_event(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_output: dict[str, Any] | str,
    duration_ms: int | None = None,
) -> SessionEvent:
    """Store a tool result event."""
    output_data = tool_output if isinstance(tool_output, dict) else {"result": tool_output}
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.TOOL_RESULT,
        tool_name=tool_name,
        tool_output=output_data,
        duration_ms=duration_ms,
    )


async def store_error_event(
    db: AsyncSession,
    session_id: str,
    error_type: str,
    error_message: str,
) -> SessionEvent:
    """Store an error event."""
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.ERROR,
        content=f"{error_type}: {error_message}",
    )


async def store_memory_inject_event(
    db: AsyncSession,
    session_id: str,
    memory_uuids: list[str],
    memory_count: int,
) -> SessionEvent:
    """Store a memory injection event."""
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.MEMORY_INJECT,
        content=f"Injected {memory_count} memory facts",
        tool_input={"uuids": memory_uuids, "count": memory_count},
    )


async def store_memory_cite_event(
    db: AsyncSession,
    session_id: str,
    cited_uuids: list[str],
) -> SessionEvent:
    """Store a memory citation event."""
    return await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.MEMORY_CITE,
        content=f"Cited {len(cited_uuids)} memory rules",
        tool_input={"uuids": cited_uuids},
    )


async def get_max_turn(db: AsyncSession, session_id: str) -> int:
    """Get the maximum turn number for a session (for resuming)."""
    result = await db.execute(
        select(SessionEvent.turn)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.turn.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row or 0


async def get_max_sequence(db: AsyncSession, session_id: str, turn: int) -> int:
    """Get the maximum sequence number for a session at a given turn."""
    result = await db.execute(
        select(SessionEvent.sequence)
        .where(SessionEvent.session_id == session_id, SessionEvent.turn == turn)
        .order_by(SessionEvent.sequence.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row or 0
