"""Canonical session ingestion service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.event_storage import get_max_sequence, get_max_turn
from app.services.memory.session_analysis import analyze_session
from app.services.session_operations import _validate_project_id, get_or_create_session
from app.services.session_scope import resolve_scope_base_path

from ._events import _adapter_for_provider, _store_events_general, _store_single_implicit_event
from ._service_helpers import (
    _apply_heartbeat_update,
    _build_new_session,
    _is_transcript_backed_session,
    _merge_metadata,
    _reconcile_transcript_session_models,
    _reconcile_transcript_session_scope,
    _update_existing_session,
    _validate_external_id,
)
from .adapters.base import ProviderSessionRef
from .models import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    SessionHeartbeatRequest,
    SessionHeartbeatResult,
    SessionUpsertRequest,
    SessionUpsertResult,
    TranscriptIngestRequest,
    TranscriptIngestResult,
)


class SessionIngestionConflict(ValueError):
    """A semantic session mutation conflict that must not be overwritten."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _validate_parent_link(
    db: AsyncSession,
    request: SessionUpsertRequest,
) -> None:
    """Validate a requested parent before persisting the relationship."""
    parent_session_id = request.parent_session_id
    if parent_session_id is None:
        return
    if request.session_id is not None and parent_session_id == request.session_id:
        raise SessionIngestionConflict(
            "session_parent_self_reference",
            "A session cannot be its own parent.",
        )

    parent, parent_exists = await get_or_create_session(db, parent_session_id)
    if not parent_exists or parent is None:
        raise SessionIngestionConflict(
            "session_parent_not_found",
            f"Parent session not found: {parent_session_id}",
        )
    if parent.project_id != request.project_id:
        raise SessionIngestionConflict(
            "session_parent_project_mismatch",
            "Parent and child sessions must belong to the same project.",
        )


async def upsert_session(
    db: AsyncSession,
    request: SessionUpsertRequest,
) -> tuple[Session, SessionUpsertResult]:
    """Create or update a session using the canonical ingestion contract."""
    await _validate_project_id(request.project_id)
    _validate_external_id(request.external_id)

    existing, is_existing = await get_or_create_session(db, request.session_id)
    if is_existing and existing is not None and existing.project_id != request.project_id:
        raise SessionIngestionConflict(
            "session_project_immutable",
            "An existing session cannot be moved to another project.",
        )
    await _validate_parent_link(db, request)

    provider = request.provider
    model = request.model
    if request.agent_slug:
        resolved = await resolve_agent(request.agent_slug, db)
        provider = resolved.provider
        model = resolved.model

    merged_metadata = _merge_metadata(
        request.provider_metadata,
        {"cwd": request.cwd} if request.cwd else None,
    )
    base_path = resolve_scope_base_path(merged_metadata, request.cwd)

    if not is_existing or existing is None:
        session = _build_new_session(request, provider, model, merged_metadata, base_path)
        db.add(session)
        await db.commit()
        return session, SessionUpsertResult(session_id=session.id, created=True)

    _update_existing_session(existing, request, provider, model, merged_metadata, base_path)
    await db.commit()
    return existing, SessionUpsertResult(session_id=existing.id, created=False)


async def heartbeat_session(
    db: AsyncSession,
    session_id: str,
    request: SessionHeartbeatRequest,
    session: Session | None = None,
) -> tuple[Session, SessionHeartbeatResult]:
    """Apply a live heartbeat update to an existing session."""
    if session is not None and session.id != session_id:
        raise SessionIngestionConflict(
            "session_identity_mismatch",
            "The supplied session does not match the heartbeat target.",
        )
    if session is None:
        session = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one_or_none()
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    _apply_heartbeat_update(session, request)
    await db.commit()
    return session, SessionHeartbeatResult(session_id=session.id, updated=True)


async def append_normalized_events(
    db: AsyncSession,
    session_id: str,
    request: AppendNormalizedEventsRequest,
    session: Session | None = None,
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
    result: AppendNormalizedEventsResult
    if len(request.events) == 1:
        event = request.events[0]
        if event.turn is None and event.sequence is None:
            result = await _store_single_implicit_event(db, session_id, event, session)
        else:
            result = await _store_events_general(db, session_id, request.events, session)
    else:
        result = await _store_events_general(db, session_id, request.events, session)

    if _is_transcript_backed_session(session):
        await _reconcile_transcript_session_models(db, session_id, session=session)
    return result


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
    await _reconcile_transcript_session_models(db, session_id)
    if append_result.events_appended == 0:
        await _reconcile_transcript_session_scope(db, session_id)
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
