"""Canonical session ingestion service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.models.session import SessionEvent
from app.services.agent_routing import resolve_agent
from app.services.event_storage import get_max_sequence, get_max_turn, store_event
from app.services.memory.session_analysis import analyze_session
from app.services.session_operations import _validate_project_id, get_or_create_session

from .adapters.base import ProviderSessionRef
from .adapters.claude_code import ClaudeCodeTranscriptAdapter
from .adapters.codex import CodexTranscriptAdapter
from .models import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    NormalizedEvent,
    SessionUpsertRequest,
    SessionUpsertResult,
    TranscriptIngestRequest,
    TranscriptIngestResult,
)


def _merge_metadata(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    """Recursively merge provider metadata dictionaries."""
    base = dict(existing or {})
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_metadata(base[key], value)
        else:
            base[key] = value
    return base


def _append_unique(values: list[str] | None, item: str | None) -> list[str]:
    """Append a value to a list if present and not already included."""
    result = list(values or [])
    if item and item not in result:
        result.append(item)
    return result


async def upsert_session(
    db: AsyncSession,
    request: SessionUpsertRequest,
) -> tuple[Session, SessionUpsertResult]:
    """Create or update a session using the canonical ingestion contract."""
    await _validate_project_id(request.project_id)
    provider = request.provider
    model = request.model
    if request.agent_slug:
        resolved = await resolve_agent(request.agent_slug, db)
        provider = resolved.provider
        model = resolved.model

    existing, is_existing = await get_or_create_session(db, request.session_id)
    if is_existing and existing is not None:
        session = existing
        created = False
    else:
        session = Session(
            id=request.session_id or str(uuid.uuid4()),
            project_id=request.project_id,
            provider=provider,
            model=model,
            status="active",
            session_type=request.session_type,
            agent_slug=request.agent_slug,
            external_id=request.external_id,
            client_id=request.client_id,
            request_source=request.request_source,
            current_branch=request.current_branch,
            provider_metadata=_merge_metadata(
                request.provider_metadata,
                {"cwd": request.cwd} if request.cwd else None,
            ),
            models_used=[model],
            providers_used=[provider],
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        created = True
        return session, SessionUpsertResult(session_id=session.id, created=created)

    session.project_id = request.project_id
    session.provider = provider
    session.model = model
    session.session_type = request.session_type
    session.agent_slug = request.agent_slug
    session.external_id = request.external_id
    session.client_id = request.client_id
    session.request_source = request.request_source
    session.current_branch = request.current_branch
    session.provider_metadata = _merge_metadata(
        session.provider_metadata,
        request.provider_metadata,
    )
    if request.cwd:
        session.provider_metadata = _merge_metadata(
            session.provider_metadata,
            {"cwd": request.cwd},
        )
    session.models_used = _append_unique(session.models_used, model)
    session.providers_used = _append_unique(session.providers_used, provider)

    await db.commit()
    await db.refresh(session)
    return session, SessionUpsertResult(session_id=session.id, created=created)


async def append_normalized_events(
    db: AsyncSession,
    session_id: str,
    request: AppendNormalizedEventsRequest,
) -> AppendNormalizedEventsResult:
    """Append normalized events to a session with forward-only sequencing."""
    if not request.events:
        current_turn = await get_max_turn(db, session_id)
        current_sequence = await get_max_sequence(db, session_id, current_turn) if current_turn else 0
        return AppendNormalizedEventsResult(
            session_id=session_id,
            events_appended=0,
            events_skipped=0,
            last_turn=current_turn or 1,
            last_sequence=current_sequence,
        )

    current_turn = await get_max_turn(db, session_id) or 1
    sequence_cache: dict[int, int] = {}
    existing_pairs = await _load_existing_pairs(
        db,
        session_id,
        {
            event.turn
            for event in request.events
            if event.turn is not None and event.sequence is not None
        },
    )

    async def next_sequence(turn: int) -> int:
        if turn not in sequence_cache:
            sequence_cache[turn] = await get_max_sequence(db, session_id, turn)
        sequence_cache[turn] += 1
        return sequence_cache[turn]

    last_turn = current_turn
    last_sequence = 0
    event_ids: list[str] = []
    events_skipped = 0
    for event in request.events:
        normalized = _normalize_event_turn_sequence(event, current_turn)
        turn = normalized.turn
        if turn is None:
            raise ValueError("Normalized event turn resolution failed")
        current_turn = max(current_turn, turn)
        if normalized.sequence is not None:
            sequence_cache[turn] = max(sequence_cache.get(turn, 0), normalized.sequence)
            if (turn, normalized.sequence) in existing_pairs:
                last_turn = turn
                last_sequence = normalized.sequence
                events_skipped += 1
                continue
        sequence = normalized.sequence if normalized.sequence is not None else await next_sequence(turn)
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
        )
        await db.flush()
        event_ids.append(str(stored_event.id))
        last_turn = turn
        last_sequence = sequence

    await db.commit()
    return AppendNormalizedEventsResult(
        session_id=session_id,
        events_appended=len(request.events) - events_skipped,
        events_skipped=events_skipped,
        last_turn=last_turn,
        last_sequence=last_sequence,
        event_ids=event_ids,
    )


def _normalize_event_turn_sequence(
    event: NormalizedEvent,
    current_turn: int,
) -> NormalizedEvent:
    """Resolve omitted turn numbers without mutating the caller's model."""
    if event.turn is not None:
        return event
    return event.model_copy(update={"turn": current_turn})


async def finalize_session(
    session_id: str,
    request: FinalizeSessionRequest | None = None,
) -> FinalizeSessionResult:
    """Finalize a session by extracting citations, feedback, and summaries."""
    payload = request or FinalizeSessionRequest()
    result = await analyze_session(
        session_id=session_id,
        citation_prefixes=payload.citation_prefixes,
        feedback_tags=payload.feedback_tags,
        summary_tags=payload.summary_tags,
        git_context=payload.git_context,
        branch=payload.branch,
        is_worktree=payload.is_worktree,
        transcript_path=payload.transcript_path,
    )
    return FinalizeSessionResult(
        session_id=result.session_id,
        citations_found=result.citations_found,
        citations_credited=result.citations_credited,
        feedback_created=result.feedback_created,
        summary_stored=result.summary_stored,
    )


async def ingest_transcript_events(
    db: AsyncSession,
    session_id: str,
    request: TranscriptIngestRequest,
) -> TranscriptIngestResult:
    """Parse a provider transcript and append normalized events idempotently."""
    adapter = _adapter_for_provider(request.provider)
    session_ref = ProviderSessionRef(
        provider_session_id=session_id,
        source_id=request.transcript_path,
    )
    events, next_checkpoint = await adapter.read_new_events(session_ref, request.checkpoint)
    boundaries = await adapter.detect_boundaries(session_ref, request.checkpoint)
    append_result = await append_normalized_events(
        db=db,
        session_id=session_id,
        request=AppendNormalizedEventsRequest(events=events),
    )
    return TranscriptIngestResult(
        session_id=session_id,
        provider=request.provider,
        transcript_path=request.transcript_path,
        events_appended=append_result.events_appended,
        events_skipped=append_result.events_skipped,
        last_turn=append_result.last_turn,
        last_sequence=append_result.last_sequence,
        event_ids=append_result.event_ids,
        next_checkpoint=next_checkpoint,
        boundaries=[boundary.boundary_type for boundary in boundaries],
    )


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


def _adapter_for_provider(provider: str) -> ClaudeCodeTranscriptAdapter | CodexTranscriptAdapter:
    """Resolve the transcript adapter for a provider."""
    normalized = provider.lower()
    if normalized in {"claude", "anthropic", "claude_code"}:
        return ClaudeCodeTranscriptAdapter()
    if normalized == "codex":
        return CodexTranscriptAdapter()
    raise ValueError(f"Unsupported transcript ingestion provider: {provider}")
