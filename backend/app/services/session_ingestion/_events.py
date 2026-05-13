"""Event storage helpers for session ingestion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import SessionEvent
from app.services.event_storage import get_max_sequence, get_max_turn, store_event

from .adapters.base import ProviderSessionRef as ProviderSessionRef  # re-exported
from .adapters.claude_code import ClaudeCodeTranscriptAdapter
from .adapters.codex import CodexTranscriptAdapter
from .models import AppendNormalizedEventsResult, NormalizedEvent

if TYPE_CHECKING:
    from app.models import Session


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


async def _lock_session_event_ingestion(db: AsyncSession, session_id: str) -> None:
    """Serialize explicit event batches per session before sequence inspection."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"session-events:{session_id}"},
    )


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
            session=session,
        )
        await db.flush()
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
        await db.rollback()
        current_turn = await get_max_turn(db, session_id) or 1
        current_seq = await get_max_sequence(db, session_id, current_turn)
        return AppendNormalizedEventsResult(
            session_id=session_id,
            events_appended=0,
            events_skipped=1,
            last_turn=current_turn,
            last_sequence=current_seq,
        )


async def _process_event(
    db: AsyncSession,
    session_id: str,
    event: NormalizedEvent,
    current_turn: int,
    sequence_cache: dict[int, int],
    existing_pairs: set[tuple[int, int]],
    session: Session | None,
) -> tuple[int, int, str | None, bool]:
    """Process one event in a batch; returns (turn, sequence, event_id, skipped)."""
    normalized = _normalize_event_turn_sequence(event, current_turn)
    turn = normalized.turn
    if turn is None:
        raise ValueError("Normalized event turn resolution failed")
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
        session=session,
    )
    await db.flush()
    return turn, sequence, str(stored_event.id), False


async def _store_events_general(
    db: AsyncSession,
    session_id: str,
    events: list[NormalizedEvent],
    session: Session | None = None,
) -> AppendNormalizedEventsResult:
    """Store a batch of normalized events with idempotent dedup."""
    await _lock_session_event_ingestion(db, session_id)
    current_turn = await get_max_turn(db, session_id) or 1
    sequence_cache: dict[int, int] = {}
    existing_pairs = await _load_existing_pairs(
        db,
        session_id,
        {e.turn for e in events if e.turn is not None and e.sequence is not None},
    )
    last_turn = current_turn
    last_sequence = 0
    event_ids: list[str] = []
    events_skipped = 0
    for event in events:
        turn, sequence, event_id, skipped = await _process_event(
            db, session_id, event, current_turn, sequence_cache, existing_pairs, session
        )
        current_turn = max(current_turn, turn)
        if skipped:
            events_skipped += 1
        elif event_id is not None:
            event_ids.append(event_id)
            existing_pairs.add((turn, sequence))
        last_turn = turn
        last_sequence = sequence
    await db.commit()
    return AppendNormalizedEventsResult(
        session_id=session_id,
        events_appended=len(events) - events_skipped,
        events_skipped=events_skipped,
        last_turn=last_turn,
        last_sequence=last_sequence,
        event_ids=event_ids,
    )
