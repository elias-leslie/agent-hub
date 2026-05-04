"""Event storage service for persisting session events to database."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent, SessionEventType
from app.services.narration_extraction import extract_narration_from_event
from app.services.session_live_activity import update_live_activity_for_event
from app.services.session_scope import (
    apply_scope_state,
    extract_tool_scope_paths,
    resolve_scope_base_path,
)

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


def _append_unique_string(values: list[str] | None, item: str | None) -> list[str]:
    existing = [v for v in (values or []) if isinstance(v, str) and v]
    if item and item not in existing:
        existing.append(item)
    return existing


def _sanitize_event_value(value: Any) -> Any:
    """Strip NUL bytes from event payloads before persistence.

    PostgreSQL rejects text and JSON strings containing ``\x00``. Session
    transcripts can include raw binary fragments, so sanitize at the shared
    storage boundary instead of letting individual ingestion paths explode.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_event_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_event_value(item) for item in value)
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            sanitized_key = key.replace("\x00", "") if isinstance(key, str) else key
            sanitized[sanitized_key] = _sanitize_event_value(item)
        return sanitized
    return value


_CHILD_SESSION_EVENT_TYPES = {
    SessionEventType.CHILD_SESSION_STARTED,
    SessionEventType.CHILD_SESSION_UPDATE,
    SessionEventType.CHILD_SESSION_BLOCKED,
    SessionEventType.CHILD_SESSION_RESULT,
}


def _source_metadata_from_session(session: Session) -> dict[str, Any]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    source_metadata = metadata.get("source_metadata")
    return source_metadata if isinstance(source_metadata, dict) else {}


def _child_session_payload(
    child_session: Session,
    *,
    child_event: SessionEvent | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "child_session_id": child_session.id,
        "status": status or child_session.status,
        "agent_slug": child_session.agent_slug,
        "project_id": child_session.project_id,
        "external_id": child_session.external_id,
        "summary": child_session.summary_oneliner,
        "workstream_status": child_session.workstream_status,
        "current_branch": child_session.current_branch,
        "observed_write_paths": child_session.observed_write_paths or [],
    }
    if child_event is not None:
        payload.update(
            {
                "child_event_id": child_event.id,
                "child_event_type": child_event.event_type,
                "child_event_content": child_event.content,
                "tool_name": child_event.tool_name,
            }
        )
    return payload


def _child_session_summary(
    child_session: Session,
    event_type: str,
    child_event: SessionEvent | None,
) -> str:
    child_label = child_session.agent_slug or child_session.id[:8]
    if event_type == SessionEventType.CHILD_SESSION_STARTED:
        return f"Child session {child_session.id} started ({child_label})"
    if event_type == SessionEventType.CHILD_SESSION_BLOCKED:
        detail = child_event.content if child_event is not None else child_session.health_detail
        return f"Child session {child_session.id} blocked: {detail or child_label}"
    if event_type == SessionEventType.CHILD_SESSION_RESULT:
        detail = child_session.summary_oneliner or child_session.health_detail or child_session.status
        return f"Child session {child_session.id} result: {detail}"
    detail = child_event.content if child_event is not None and child_event.content else child_session.health_detail
    return f"Child session {child_session.id} update: {detail or child_label}"


async def store_child_session_lifecycle_event(
    db: AsyncSession,
    child_session: Session,
    event_type: str,
    *,
    child_event: SessionEvent | None = None,
    summary: str | None = None,
    status: str | None = None,
) -> SessionEvent | None:
    """Store a child-lane lifecycle event on the parent supervisor session."""
    parent_session_id = getattr(child_session, "parent_session_id", None)
    if not parent_session_id:
        return None
    if event_type not in _CHILD_SESSION_EVENT_TYPES:
        return None
    source_metadata = _source_metadata_from_session(child_session)
    return await store_event(
        db=db,
        session_id=parent_session_id,
        event_type=event_type,
        content=summary or _child_session_summary(child_session, event_type, child_event),
        tool_output=_child_session_payload(child_session, child_event=child_event, status=status),
        agent_id=child_session.agent_slug,
        agent_name=child_session.agent_slug,
        transport=source_metadata.get("transport"),
        surface=source_metadata.get("surface"),
        chat_id=source_metadata.get("chat_id"),
        message_id=source_metadata.get("message_id"),
        pane_id=source_metadata.get("pane_id"),
        source_client=source_metadata.get("source_client"),
    )


async def _mirror_child_event_to_parent(
    db: AsyncSession,
    child_session: Session | None,
    child_event: SessionEvent,
) -> None:
    if child_session is None or not getattr(child_session, "parent_session_id", None):
        return
    if child_event.event_type in _CHILD_SESSION_EVENT_TYPES:
        return
    event_type: str | None
    if child_event.event_type == SessionEventType.ERROR:
        event_type = SessionEventType.CHILD_SESSION_BLOCKED
    elif child_event.event_type in {
        SessionEventType.ASSISTANT_MESSAGE,
        SessionEventType.THINKING,
        SessionEventType.TOOL_USE,
        SessionEventType.TOOL_RESULT,
    }:
        event_type = SessionEventType.CHILD_SESSION_UPDATE
    else:
        event_type = None
    if event_type is None:
        return
    await store_child_session_lifecycle_event(
        db,
        child_session,
        event_type,
        child_event=child_event,
    )


def _reconcile_session_from_event(
    session: Session,
    *,
    event_type: str,
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    model_used: str | None,
    agent_id: str | None,
) -> None:
    if model_used:
        session.models_used = _append_unique_string(getattr(session, "models_used", None), model_used)
        if not agent_id:
            session.model = model_used
    if str(event_type) != SessionEventType.TOOL_USE:
        return
    provider_metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    base_path = resolve_scope_base_path(provider_metadata, None)
    observed_reads, observed_writes = extract_tool_scope_paths(
        tool_name,
        tool_input,
        base_path=base_path,
    )
    if not observed_reads and not observed_writes:
        return
    apply_scope_state(
        session,
        base_path=base_path,
        observed_read_paths=observed_reads,
        observed_write_paths=observed_writes,
    )


async def _resolve_turn_sequence(db: AsyncSession, session_id: str) -> tuple[int, int]:
    """Sync sequencer from DB if needed, return (turn, sequence)."""
    sequencer = get_sequencer()
    if session_id not in sequencer._sessions:
        current_turn = await get_max_turn(db, session_id)
        current_sequence = (
            await get_max_sequence(db, session_id, current_turn) if current_turn else 0
        )
        if current_turn:
            sequencer.set_turn(session_id, current_turn, current_sequence)
    return sequencer.get_turn_sequence(session_id)


def _touch_session(
    parent_session: Session,
    *,
    event_type: str,
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    tool_output: dict[str, Any] | None,
    content: str | None,
    model_used: str | None,
    agent_id: str | None,
) -> None:
    _reconcile_session_from_event(
        parent_session,
        event_type=event_type,
        tool_name=tool_name,
        tool_input=tool_input,
        model_used=model_used,
        agent_id=agent_id,
    )
    update_live_activity_for_event(
        parent_session,
        event_type=event_type,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        content=content,
        model_used=model_used,
    )
    touched_at = datetime.now(UTC)
    parent_session.updated_at = touched_at
    parent_session.last_activity_at = touched_at


async def _maybe_extract_narration(
    db: AsyncSession,
    session_id: str,
    event_type: str,
    content: str | None,
    session: Session | None,
) -> None:
    """Extract narration tags from assistant messages, silently ignoring failures."""
    if event_type != SessionEventType.ASSISTANT_MESSAGE or not content:
        return
    try:
        await extract_narration_from_event(
            db, session_id=session_id, event_type=event_type,
            content=content, session=session,
        )
    except Exception:
        logger.debug("Failed to extract narration tags", exc_info=True)


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
    transport: str | None = None,
    surface: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    pane_id: str | None = None,
    source_client: str | None = None,
    session: Session | None = None,
) -> SessionEvent:
    """Store a single event to the database.

    If turn/sequence not provided, auto-generates from sequencer.
    """
    if turn is None or sequence is None:
        turn, sequence = await _resolve_turn_sequence(db, session_id)

    role = _sanitize_event_value(role)
    content = _sanitize_event_value(content)
    tool_name = _sanitize_event_value(tool_name)
    tool_input = _sanitize_event_value(tool_input)
    tool_output = _sanitize_event_value(tool_output)
    model_used = _sanitize_event_value(model_used)
    agent_id = _sanitize_event_value(agent_id)
    agent_name = _sanitize_event_value(agent_name)
    transport = _sanitize_event_value(transport)
    surface = _sanitize_event_value(surface)
    chat_id = _sanitize_event_value(chat_id)
    message_id = _sanitize_event_value(message_id)
    pane_id = _sanitize_event_value(pane_id)
    source_client = _sanitize_event_value(source_client)

    event = SessionEvent(
        session_id=session_id, turn=turn, sequence=sequence, event_type=event_type,
        role=role, content=content, tool_name=tool_name, tool_input=tool_input,
        tool_output=tool_output, tokens=tokens, duration_ms=duration_ms,
        model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        transport=transport, surface=surface, chat_id=chat_id,
        message_id=message_id, pane_id=pane_id, source_client=source_client,
    )
    db.add(event)

    parent_session = session or await db.get(Session, session_id)
    if parent_session is not None:
        _touch_session(
            parent_session,
            event_type=str(event_type),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            content=content,
            model_used=model_used,
            agent_id=agent_id,
        )

    await _maybe_extract_narration(db, session_id, event_type, content, parent_session)
    await _mirror_child_event_to_parent(db, parent_session, event)
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
    duration_ms: int | None = None,
    transport: str | None = None,
    surface: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    pane_id: str | None = None,
    source_client: str | None = None,
) -> SessionEvent:
    """Store a message event (user, assistant, or system)."""
    event_type_map = {
        "user": SessionEventType.USER_MESSAGE,
        "assistant": SessionEventType.ASSISTANT_MESSAGE,
        "system": SessionEventType.SYSTEM_MESSAGE,
    }
    return await store_event(
        db=db, session_id=session_id,
        event_type=event_type_map.get(role, SessionEventType.USER_MESSAGE),
        role=role, content=content, tokens=tokens, duration_ms=duration_ms,
        model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        transport=transport, surface=surface, chat_id=chat_id,
        message_id=message_id, pane_id=pane_id, source_client=source_client,
    )


async def store_thinking_event(
    db: AsyncSession,
    session_id: str,
    thinking_content: str,
    tokens: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    transport: str | None = None,
    surface: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    pane_id: str | None = None,
    source_client: str | None = None,
) -> SessionEvent:
    """Store a thinking/reasoning event."""
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.THINKING,
        content=thinking_content, tokens=tokens,
        model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        transport=transport, surface=surface, chat_id=chat_id,
        message_id=message_id, pane_id=pane_id, source_client=source_client,
    )


async def store_tool_use_event(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    duration_ms: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    transport: str | None = None,
    surface: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    pane_id: str | None = None,
    source_client: str | None = None,
) -> SessionEvent:
    """Store a tool use event."""
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.TOOL_USE,
        tool_name=tool_name, tool_input=tool_input, duration_ms=duration_ms,
        model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        transport=transport, surface=surface, chat_id=chat_id,
        message_id=message_id, pane_id=pane_id, source_client=source_client,
    )


def _extract_tool_result_content(output_data: dict[str, Any]) -> str | None:
    """Extract a text summary from tool_output for the content column.

    Tries common keys in order: result, content, output, message.
    Falls back to None if no usable text found.
    """
    for key in ("result", "content", "output", "message"):
        val = output_data.get(key)
        if val and isinstance(val, str):
            return val[:2000]
    if len(output_data) == 1:
        val = next(iter(output_data.values()))
        if isinstance(val, str):
            return val[:2000]
    return None


async def store_tool_result_event(
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    tool_output: dict[str, Any] | str,
    duration_ms: int | None = None,
    model_used: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    transport: str | None = None,
    surface: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    pane_id: str | None = None,
    source_client: str | None = None,
) -> SessionEvent:
    """Store a tool result event."""
    output_data = tool_output if isinstance(tool_output, dict) else {"result": tool_output}
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.TOOL_RESULT,
        tool_name=tool_name, content=_extract_tool_result_content(output_data),
        tool_output=output_data, duration_ms=duration_ms,
        model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        transport=transport, surface=surface, chat_id=chat_id,
        message_id=message_id, pane_id=pane_id, source_client=source_client,
    )


async def store_error_event(
    db: AsyncSession,
    session_id: str,
    error_type: str,
    error_message: str,
    agent_id: str | None = None,
    agent_name: str | None = None,
    model_used: str | None = None,
) -> SessionEvent:
    """Store an error event."""
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.ERROR,
        content=f"{error_type}: {error_message}",
        agent_id=agent_id, agent_name=agent_name, model_used=model_used,
    )


async def store_memory_inject_event(
    db: AsyncSession,
    session_id: str,
    memory_uuids: list[str],
    memory_count: int,
    reference_selected_uuids: list[str] | None = None,
    reference_index_uuids: list[str] | None = None,
    memory_debug: dict[str, Any] | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> SessionEvent:
    """Store a memory injection event."""
    selected = reference_selected_uuids or []
    indexed = reference_index_uuids or []
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.MEMORY_INJECT,
        content=f"Injected {memory_count} memory facts (refs selected={len(selected)} index={len(indexed)})",
        tool_input={
            "uuids": memory_uuids,
            "count": memory_count,
            "reference_selected_count": len(selected),
            "reference_index_count": len(indexed),
            "reference_selected_uuids": selected,
            "reference_index_uuids": indexed,
            "memory_debug": memory_debug or {},
        },
        agent_id=agent_id, agent_name=agent_name,
    )


async def store_memory_cite_event(
    db: AsyncSession,
    session_id: str,
    cited_uuids: list[str],
    agent_id: str | None = None,
    agent_name: str | None = None,
    model_used: str | None = None,
) -> SessionEvent:
    """Store a memory citation event."""
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.MEMORY_CITE,
        content=f"Cited {len(cited_uuids)} memory rules",
        tool_input={"uuids": cited_uuids},
        agent_id=agent_id, agent_name=agent_name, model_used=model_used,
    )


async def store_subagent_result_event(
    db: AsyncSession,
    session_id: str,
    subagent_id: str,
    subagent_name: str,
    content: str,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_used: str | None = None,
    duration_ms: int | None = None,
) -> SessionEvent:
    """Store a subagent result event (announce-back to parent session)."""
    return await store_event(
        db=db, session_id=session_id, event_type=SessionEventType.SUBAGENT_RESULT,
        content=content,
        tool_output={
            "subagent_id": subagent_id, "subagent_name": subagent_name,
            "status": status, "input_tokens": input_tokens, "output_tokens": output_tokens,
        },
        tokens=input_tokens + output_tokens, duration_ms=duration_ms,
        model_used=model_used, agent_id=subagent_id, agent_name=subagent_name,
    )


async def get_max_turn(db: AsyncSession, session_id: str) -> int:
    """Get the maximum turn number for a session (for resuming)."""
    result = await db.execute(
        select(SessionEvent.turn)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.turn.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or 0


async def get_max_sequence(db: AsyncSession, session_id: str, turn: int) -> int:
    """Get the maximum sequence number for a session at a given turn."""
    result = await db.execute(
        select(SessionEvent.sequence)
        .where(SessionEvent.session_id == session_id, SessionEvent.turn == turn)
        .order_by(SessionEvent.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or 0
