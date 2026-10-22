"""Event storage helpers for session ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import SessionEvent
from app.services.event_storage import (
    _build_session_event,
    get_max_sequence,
    get_max_turn,
    get_sequencer,
    lock_session_event_ingestion,
    store_event,
)

from .adapters.base import ProviderSessionRef as ProviderSessionRef  # re-exported
from .adapters.claude_code import ClaudeCodeTranscriptAdapter
from .adapters.codex import CodexTranscriptAdapter
from .models import AppendNormalizedEventsResult, NormalizedEvent

if TYPE_CHECKING:
    from app.models import Session


_FILE_SOURCE_ID = r"^((assistant|user|response_item|event_msg):)[0-9]+:([0-9]+:(byte|ordinal):[0-9]+:[0-9a-f]{16}:[0-9]+)$"


def source_identity(source_id: str) -> str:
    """A mount device number is not part of a transcript record's identity.

    Keep the inode, byte/ordinal position, exact record digest and block index.
    Native provider IDs and all other caller identities remain unchanged.
    """
    return re.sub(_FILE_SOURCE_ID, r"\1\3", source_id)


def _normalize_event_turn_sequence(
    event: NormalizedEvent,
    current_turn: int,
) -> NormalizedEvent:
    """Resolve omitted turn numbers without mutating the caller's model."""
    if event.turn is not None:
        return event
    return event.model_copy(update={"turn": current_turn})


async def _load_existing_pairs(
    db: AsyncSession,
    session_id: str,
    turns: set[int],
) -> set[tuple[int, int]]:
    """Load already-persisted turn/sequence pairs for idempotent append."""
    if not turns:
        return set()
    result = await db.execute(
        select(SessionEvent.turn, SessionEvent.sequence).where(
            SessionEvent.session_id == session_id,
            SessionEvent.turn.in_(turns),
        )
    )
    return {(turn, sequence) for turn, sequence in result.all()}


async def _load_existing_source_events(
    db: AsyncSession, session_id: str, source_ids: set[str]
) -> dict[str, SessionEvent]:
    if not source_ids:
        return {}
    result = await db.execute(
        select(SessionEvent).where(
            SessionEvent.session_id == session_id,
            or_(SessionEvent.source_event_id.in_(source_ids),
                func.regexp_replace(SessionEvent.source_event_id, _FILE_SOURCE_ID, r"\1\3").in_(
                    {source_identity(source_id) for source_id in source_ids}
                )),
        ).order_by(SessionEvent.created_at, SessionEvent.id)
    )
    rows = result.scalars().all()
    found = {event.source_event_id: event for event in rows if event.source_event_id}
    canonical: dict[str, SessionEvent] = {}
    for event in rows:
        if event.source_event_id:
            canonical.setdefault(source_identity(event.source_event_id), event)
    for source_id in source_ids:
        if source_identity(source_id) in canonical:
            found[source_id] = canonical[source_identity(source_id)]
    return found


def _source_event_fingerprint(
    event: NormalizedEvent | SessionEvent,
    *,
    turn: int,
    sequence: int,
) -> str:
    """Compare replayed native identities without trusting the identity alone."""
    fields: dict[str, Any] = {
        key: getattr(event, key, None)
        for key in (
            "event_type", "role", "content", "tool_name", "call_id",
            "tool_input", "tool_output", "tokens", "duration_ms", "model_used",
            "agent_id", "agent_name", "transport", "surface", "chat_id",
            "message_id", "pane_id", "source_client", "source_event_id",
            "source_timestamp", "usage",
        )
    }
    # Replay compares the same redacted/compacted representation as storage.
    # Otherwise a native credential-shaped string conflicts with its own
    # persisted redaction on an unchanged-source replay.
    canonical = _build_session_event("fingerprint", turn, sequence, **fields)
    fields = {key: getattr(canonical, key) for key in fields}
    if fields["source_event_id"]:
        fields["source_event_id"] = source_identity(fields["source_event_id"])
    fields.update({"turn": turn, "sequence": sequence})
    return hashlib.sha256(json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()).hexdigest()


def _adapter_for_provider(provider: str) -> ClaudeCodeTranscriptAdapter | CodexTranscriptAdapter:
    """Resolve the transcript adapter for a provider."""
    normalized = provider.lower()
    if normalized in {"claude", "anthropic", "claude_code"}:
        return ClaudeCodeTranscriptAdapter()
    if normalized == "codex":
        return CodexTranscriptAdapter()
    raise ValueError(f"Unsupported transcript ingestion provider: {provider}")


async def _store_single_implicit_event(
    db: AsyncSession,
    session_id: str,
    event: NormalizedEvent,
    session: Session | None = None,
    *,
    commit: bool = True,
) -> AppendNormalizedEventsResult:
    """Fast path: store a single event with auto-assigned turn and sequence."""
    try:
        stored_event = await store_event(
            db=db,
            session_id=session_id,
            event_type=event.event_type,
            role=event.role,
            content=event.content,
            tool_name=event.tool_name,
            call_id=event.call_id,
            tool_input=event.tool_input,
            tool_output=event.tool_output,
            tokens=event.tokens,
            duration_ms=event.duration_ms,
            model_used=event.model_used,
            agent_id=event.agent_id,
            agent_name=event.agent_name,
            transport=event.transport,
            surface=event.surface,
            chat_id=event.chat_id,
            message_id=event.message_id,
            pane_id=event.pane_id,
            source_client=event.source_client,
            source_event_id=event.source_event_id,
            source_timestamp=event.source_timestamp,
            usage=event.usage,
            session=session,
        )
        await db.flush()
        if commit:
            await db.commit()
        return AppendNormalizedEventsResult(
            session_id=session_id,
            events_appended=1,
            events_skipped=0,
            last_turn=stored_event.turn,
            last_sequence=stored_event.sequence,
            event_ids=[str(stored_event.id)],
        )
    except IntegrityError:
        if not commit:
            raise
        # An implicit event has no identity of its own, so a uq_session_turn_sequence
        # collision means the in-process sequencer is stale (another path stored
        # explicit turn/sequence pairs), not a replay. Retry once under the
        # session lock with DB-derived numbering instead of dropping the event.
        # The rollback expired ``session``; pass None so nothing lazy-loads it.
        await db.rollback()
        result = await _store_events_general(db, session_id, [event], None, commit=True)
        get_sequencer().set_turn(session_id, result.last_turn, result.last_sequence)
        return result


async def _process_event(
    db: AsyncSession,
    session_id: str,
    event: NormalizedEvent,
    current_turn: int,
    sequence_cache: dict[int, int],
    existing_pairs: set[tuple[int, int]],
    existing_source_events: dict[str, NormalizedEvent | SessionEvent],
    session: Session | None,
) -> tuple[int, int, str | None, bool]:
    """Process one event in a batch; returns (turn, sequence, event_id, skipped)."""
    normalized = _normalize_event_turn_sequence(event, current_turn)
    turn = normalized.turn
    if turn is None:
        raise ValueError("Normalized event turn resolution failed")
    if normalized.source_event_id and normalized.source_event_id in existing_source_events:
        existing = existing_source_events[normalized.source_event_id]
        existing_turn = getattr(existing, "turn", None) or turn
        existing_sequence = getattr(existing, "sequence", None)
        sequence = normalized.sequence or existing_sequence or sequence_cache.get(turn, 0)
        if _source_event_fingerprint(
            normalized,
            turn=normalized.turn or existing_turn,
            sequence=sequence,
        ) != _source_event_fingerprint(
            existing,
            turn=existing_turn,
            sequence=existing_sequence or sequence,
        ):
            raise ValueError(
                "Native source event identity was replayed with different content"
            )
        return turn, sequence, None, True
    if normalized.sequence is not None:
        sequence_cache[turn] = max(sequence_cache.get(turn, 0), normalized.sequence)
        if (turn, normalized.sequence) in existing_pairs:
            return turn, normalized.sequence, None, True
    if normalized.sequence is not None:
        sequence = normalized.sequence
    else:
        if turn not in sequence_cache:
            sequence_cache[turn] = await get_max_sequence(db, session_id, turn)
        sequence_cache[turn] += 1
        sequence = sequence_cache[turn]
    sequence_cache[turn] = max(sequence_cache.get(turn, 0), sequence)
    stored_event = await store_event(
        db=db,
        session_id=session_id,
        event_type=normalized.event_type,
        turn=turn,
        sequence=sequence,
        role=normalized.role,
        content=normalized.content,
        tool_name=normalized.tool_name,
        call_id=normalized.call_id,
        tool_input=normalized.tool_input,
        tool_output=normalized.tool_output,
        tokens=normalized.tokens,
        duration_ms=normalized.duration_ms,
        model_used=normalized.model_used,
        agent_id=normalized.agent_id,
        agent_name=normalized.agent_name,
        transport=normalized.transport,
        surface=normalized.surface,
        chat_id=normalized.chat_id,
        message_id=normalized.message_id,
        pane_id=normalized.pane_id,
        source_client=normalized.source_client,
        source_event_id=normalized.source_event_id,
        source_timestamp=normalized.source_timestamp,
        usage=normalized.usage,
        session=session,
    )
    await db.flush()
    return turn, sequence, str(stored_event.id), False


async def _store_events_general(
    db: AsyncSession,
    session_id: str,
    events: list[NormalizedEvent],
    session: Session | None = None,
    *,
    commit: bool = True,
) -> AppendNormalizedEventsResult:
    """Store a batch of normalized events with idempotent dedup."""
    await lock_session_event_ingestion(db, session_id)
    current_turn = await get_max_turn(db, session_id) or 1
    sequence_cache: dict[int, int] = {}
    existing_pairs = await _load_existing_pairs(
        db,
        session_id,
        {e.turn for e in events if e.turn is not None and e.sequence is not None},
    )
    stored_source_events = await _load_existing_source_events(
        db, session_id, {e.source_event_id for e in events if e.source_event_id}
    )
    existing_source_events: dict[str, NormalizedEvent | SessionEvent] = {
        key: value for key, value in stored_source_events.items()
    }
    last_turn = current_turn
    last_sequence = 0
    event_ids: list[str] = []
    events_skipped = 0
    for event in events:
        turn, sequence, event_id, skipped = await _process_event(
            db, session_id, event, current_turn, sequence_cache, existing_pairs,
            existing_source_events, session
        )
        current_turn = max(current_turn, turn)
        if skipped:
            events_skipped += 1
        elif event_id is not None:
            event_ids.append(event_id)
            existing_pairs.add((turn, sequence))
            if event.source_event_id:
                existing_source_events[event.source_event_id] = event.model_copy(
                    update={"turn": turn, "sequence": sequence}
                )
        last_turn = turn
        last_sequence = sequence
    if commit:
        await db.commit()
    return AppendNormalizedEventsResult(
        session_id=session_id,
        events_appended=len(events) - events_skipped,
        events_skipped=events_skipped,
        last_turn=last_turn,
        last_sequence=last_sequence,
        event_ids=event_ids,
    )
