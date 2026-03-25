"""Canonical session ingestion service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH
from app.services.agent_routing import resolve_agent
from app.services.event_storage import get_max_sequence, get_max_turn
from app.services.memory.session_analysis import analyze_session
from app.services.session_live_activity import apply_live_activity_heartbeat
from app.services.session_operations import _validate_project_id, get_or_create_session
from app.services.session_scope import normalize_scope_paths

from ._events import _adapter_for_provider, _store_events_general, _store_single_implicit_event
from ._scope import _apply_scope_state, _scope_base_path
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


def _validate_external_id(external_id: str | None) -> None:
    """Reject external IDs that exceed the persisted session field length."""
    if external_id and len(external_id) > EXTERNAL_ID_MAX_LENGTH:
        raise ValueError(
            f"external_id exceeds max length {EXTERNAL_ID_MAX_LENGTH}: {len(external_id)}"
        )


def _build_new_session(
    request: SessionUpsertRequest,
    provider: str | None,
    model: str | None,
    merged_metadata: dict[str, Any],
    base_path: str | None,
) -> Session:
    """Construct a new Session ORM object from an upsert request."""
    now = datetime.now(UTC)
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
        parent_session_id=request.parent_session_id,
        provider_metadata=merged_metadata,
        models_used=[model],
        providers_used=[provider],
        created_at=now,
        updated_at=now,
    )
    _apply_scope_state(
        session,
        base_path=base_path,
        declared_scope_paths=request.declared_scope_paths,
        observed_read_paths=request.observed_read_paths,
        observed_write_paths=request.observed_write_paths,
        scope_confidence=request.scope_confidence,
    )
    return session


def _update_existing_session(
    session: Session,
    request: SessionUpsertRequest,
    provider: str | None,
    model: str | None,
    merged_metadata: dict[str, Any],
    base_path: str | None,
) -> None:
    """Apply upsert-request fields to an existing session."""
    session.project_id = request.project_id
    if provider is not None:
        session.provider = provider
    if model is not None:
        session.model = model
    session.session_type = request.session_type
    session.agent_slug = request.agent_slug
    session.external_id = request.external_id
    session.client_id = request.client_id
    session.request_source = request.request_source
    session.current_branch = request.current_branch
    session.status = "active"
    if request.parent_session_id is not None:
        session.parent_session_id = request.parent_session_id
    session.provider_metadata = _merge_metadata(session.provider_metadata, merged_metadata)
    session.models_used = _append_unique(session.models_used, model)
    session.providers_used = _append_unique(session.providers_used, provider)
    _apply_scope_state(
        session,
        base_path=base_path,
        declared_scope_paths=request.declared_scope_paths,
        observed_read_paths=request.observed_read_paths,
        observed_write_paths=request.observed_write_paths,
        scope_confidence=request.scope_confidence,
    )
    session.updated_at = datetime.now(UTC)


async def upsert_session(
    db: AsyncSession,
    request: SessionUpsertRequest,
) -> tuple[Session, SessionUpsertResult]:
    """Create or update a session using the canonical ingestion contract."""
    await _validate_project_id(request.project_id)
    _validate_external_id(request.external_id)
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
    base_path = _scope_base_path(merged_metadata, request.cwd)

    existing, is_existing = await get_or_create_session(db, request.session_id)
    if not is_existing or existing is None:
        session = _build_new_session(request, provider, model, merged_metadata, base_path)
        db.add(session)
        await db.commit()
        return session, SessionUpsertResult(session_id=session.id, created=True)

    _update_existing_session(existing, request, provider, model, merged_metadata, base_path)
    await db.commit()
    return existing, SessionUpsertResult(session_id=existing.id, created=False)


def _apply_heartbeat_update(session: Session, request: SessionHeartbeatRequest) -> None:
    """Apply all in-place field mutations for a heartbeat request."""
    metadata = _merge_metadata(session.provider_metadata, request.provider_metadata)
    if request.cwd:
        metadata = _merge_metadata(metadata, {"cwd": request.cwd})
    session.provider_metadata = metadata

    if request.current_branch is not None:
        session.current_branch = request.current_branch
    if request.client_id is not None:
        session.client_id = request.client_id
    if request.request_source is not None:
        session.request_source = request.request_source
    if request.status is not None:
        session.status = request.status

    base_path = _scope_base_path(metadata, request.cwd)
    _apply_scope_state(
        session,
        base_path=base_path,
        declared_scope_paths=request.declared_scope_paths,
        observed_read_paths=request.active_read_paths,
        observed_write_paths=request.active_write_paths,
        scope_confidence=request.scope_confidence,
    )

    heartbeat_at = request.heartbeat_at or datetime.now(UTC)
    session.last_heartbeat_at = heartbeat_at
    apply_live_activity_heartbeat(
        session,
        heartbeat_at=heartbeat_at.isoformat(),
        phase=request.phase,
        status=request.status,
        summary=request.summary,
        current_tool_name=request.current_tool_name,
        current_command=request.current_command,
        last_event_type=request.last_event_type,
        active_read_paths=normalize_scope_paths(request.active_read_paths, base_path),
        active_write_paths=normalize_scope_paths(request.active_write_paths, base_path),
    )
    session.updated_at = datetime.now(UTC)


async def heartbeat_session(
    db: AsyncSession,
    session_id: str,
    request: SessionHeartbeatRequest,
) -> tuple[Session, SessionHeartbeatResult]:
    """Apply a live heartbeat update to an existing session."""
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
    if len(request.events) == 1:
        event = request.events[0]
        if event.turn is None and event.sequence is None:
            return await _store_single_implicit_event(db, session_id, event, session)
    return await _store_events_general(db, session_id, request.events, session)


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
