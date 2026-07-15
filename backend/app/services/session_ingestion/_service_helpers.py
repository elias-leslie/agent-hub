"""Internal helpers for session_ingestion/service.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH
from app.services.session_live_activity import apply_live_activity_heartbeat
from app.services.session_scope import (
    apply_scope_state,
    extract_tool_scope_paths,
    merge_scope_paths,
    normalize_scope_paths,
    resolve_scope_base_path,
)

from .models import SessionHeartbeatRequest, SessionUpsertRequest

# ---------------------------------------------------------------------------
# Pure utility helpers
# ---------------------------------------------------------------------------


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


def _dedupe_strings(values: list[str]) -> list[str]:
    """Preserve first-seen order while removing duplicate strings."""
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _is_transcript_backed_session(session: Session | None) -> bool:
    """Return whether a session carries transcript metadata."""
    if session is None or not isinstance(session.provider_metadata, dict):
        return False
    transcript_path = session.provider_metadata.get("transcript_path")
    return isinstance(transcript_path, str) and bool(transcript_path)


def _validate_external_id(external_id: str | None) -> None:
    """Reject external IDs that exceed the persisted session field length."""
    if external_id and len(external_id) > EXTERNAL_ID_MAX_LENGTH:
        raise ValueError(
            f"external_id exceeds max length {EXTERNAL_ID_MAX_LENGTH}: {len(external_id)}"
        )


# ---------------------------------------------------------------------------
# Session ORM construction / mutation helpers
# ---------------------------------------------------------------------------


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
    apply_scope_state(
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
    apply_scope_state(
        session,
        base_path=base_path,
        declared_scope_paths=request.declared_scope_paths,
        observed_read_paths=request.observed_read_paths,
        observed_write_paths=request.observed_write_paths,
        scope_confidence=request.scope_confidence,
    )
    session.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Event model extraction
# ---------------------------------------------------------------------------


def _extract_event_models(
    event_rows: list,
) -> tuple[list[str], list[str]]:
    """Collect all model names and top-level model names from event rows."""
    all_models: list[str] = []
    top_level_models: list[str] = []
    for model_used, agent_id in event_rows:
        if not isinstance(model_used, str) or not model_used:
            continue
        all_models.append(model_used)
        if not isinstance(agent_id, str) or not agent_id:
            top_level_models.append(model_used)
    return all_models, top_level_models


# ---------------------------------------------------------------------------
# Heartbeat mutation helper
# ---------------------------------------------------------------------------


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

    base_path = resolve_scope_base_path(metadata, request.cwd)
    apply_scope_state(
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


# ---------------------------------------------------------------------------
# Transcript model reconciliation
# ---------------------------------------------------------------------------


async def _reconcile_transcript_session_models(
    db: AsyncSession,
    session_id: str,
    session: Session | None = None,
) -> None:
    """Rebuild transcript-backed model fields from persisted event evidence."""
    if session is None:
        session = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one_or_none()
    if session is None:
        return

    event_rows = (
        await db.execute(
            select(SessionEvent.model_used, SessionEvent.agent_id)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.turn, SessionEvent.sequence)
        )
    ).all()
    if not event_rows:
        return

    all_models, top_level_models = _extract_event_models(event_rows)
    normalized_models = _dedupe_strings(all_models)
    normalized_top_level = _dedupe_strings(top_level_models)
    if not normalized_models:
        return

    updated = False
    if session.models_used != normalized_models:
        session.models_used = normalized_models
        updated = True

    normalized_model = normalized_top_level[-1] if normalized_top_level else None
    if normalized_model and session.model != normalized_model:
        session.model = normalized_model
        updated = True

    if updated:
        session.updated_at = datetime.now(UTC)
        await db.commit()


async def _reconcile_transcript_session_scope(
    db: AsyncSession,
    session_id: str,
    session: Session | None = None,
) -> None:
    """Backfill transcript-backed scope from persisted tool events when the row is still unscoped."""
    if session is None:
        session = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one_or_none()
    if session is None:
        return
    if not _is_transcript_backed_session(session):
        return
    if session.scope_confidence in {"declared", "observed_write", "observed_read"}:
        return

    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    base_path = resolve_scope_base_path(metadata, None)
    declared_paths = normalize_scope_paths(getattr(session, "declared_scope_paths", None), base_path)
    observed_reads = normalize_scope_paths(getattr(session, "observed_read_paths", None), base_path)
    observed_writes = normalize_scope_paths(getattr(session, "observed_write_paths", None), base_path)
    if not (declared_paths or observed_reads or observed_writes):
        tool_rows = (
            await db.execute(
                select(SessionEvent.tool_name, SessionEvent.tool_input)
                .where(
                    SessionEvent.session_id == session_id,
                    SessionEvent.event_type == "tool_use",
                )
                .order_by(SessionEvent.turn, SessionEvent.sequence)
            )
        ).all()
        for tool_name, tool_input in tool_rows:
            tool_reads, tool_writes = extract_tool_scope_paths(
                tool_name,
                tool_input if isinstance(tool_input, dict) else None,
                base_path=base_path,
            )
            observed_reads = merge_scope_paths(observed_reads, tool_reads)
            observed_writes = merge_scope_paths(observed_writes, tool_writes)
    if not (declared_paths or observed_reads or observed_writes):
        return

    previous_declared = list(session.declared_scope_paths or [])
    previous_reads = list(session.observed_read_paths or [])
    previous_writes = list(session.observed_write_paths or [])
    previous_confidence = session.scope_confidence
    apply_scope_state(
        session,
        base_path=base_path,
        declared_scope_paths=declared_paths,
        observed_read_paths=observed_reads,
        observed_write_paths=observed_writes,
    )
    if (
        session.declared_scope_paths != previous_declared
        or session.observed_read_paths != previous_reads
        or session.observed_write_paths != previous_writes
        or session.scope_confidence != previous_confidence
    ):
        session.updated_at = datetime.now(UTC)
        await db.commit()
