"""Canonical session ingestion service."""

from __future__ import annotations

import asyncio

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.event_storage import get_max_sequence, get_max_turn, lock_session_event_ingestion
from app.services.memory.session_analysis import analyze_session
from app.services.session_operations import _validate_project_id, get_or_create_session
from app.services.session_scope import resolve_scope_base_path

from ._events import _adapter_for_provider, _store_events_general, _store_single_implicit_event
from ._native_provenance import validate_native_provenance
from ._service_helpers import (
    _apply_heartbeat_update,
    _build_new_session,
    _is_transcript_backed_session,
    _merge_metadata,
    _reconcile_transcript_session_models,
    _reconcile_transcript_session_scope,
    _session_if_loaded,
    _update_existing_session,
    _validate_external_id,
)
from .adapters.base import ProviderSessionRef
from .adapters.transcript_parsers import _load_parse_checkpoint, inspect_transcript_source
from .models import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    SessionHeartbeatRequest,
    SessionHeartbeatResult,
    SessionModelEvidence,
    SessionUpsertRequest,
    SessionUpsertResult,
    TranscriptIngestRequest,
    TranscriptIngestResult,
    validated_native_model_evidence,
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


async def _validate_native_parent_project(db: AsyncSession, session: Session) -> None:
    """Do not refresh legacy native parent links across project boundaries."""
    if session.parent_session_id is None:
        return
    parent = await db.get(Session, session.parent_session_id)
    if parent is None:
        raise SessionIngestionConflict("session_parent_not_found", "The native parent is not registered.")
    if parent.project_id != session.project_id:
        raise SessionIngestionConflict("session_parent_project_mismatch", "Native parent and child must belong to the same project.")


async def upsert_session(
    db: AsyncSession,
    request: SessionUpsertRequest,
) -> tuple[Session, SessionUpsertResult]:
    """Create or update a session using the canonical ingestion contract."""
    await _validate_project_id(request.project_id)
    _validate_external_id(request.external_id)

    incoming_metadata = _merge_metadata({}, request.provider_metadata)
    if request.work_role is not None:
        incoming_metadata = _merge_metadata(incoming_metadata, {
            "work_role": request.work_role.model_dump(exclude_none=True),
        })
    request = request.model_copy(update={"provider_metadata": incoming_metadata})
    existing, is_existing = await get_or_create_session(db, request.session_id)
    if is_existing and existing is not None and existing.project_id != request.project_id:
        raise SessionIngestionConflict(
            "session_project_immutable",
            "An existing session cannot be moved to another project.",
        )
    if existing is not None and existing.provider == "codex" and (
        (existing.provider_metadata or {}).get("transcript_path") and request.provider.lower() != "codex"
    ):
        raise SessionIngestionConflict("session_provider_immutable", "A native Codex session cannot change provider.")
    if existing is not None:
        if request.provider.lower() == "codex" or request.session_type == "pi":
            await lock_session_event_ingestion(db, existing.id)
        await db.refresh(existing, with_for_update=True)
    await _validate_parent_link(db, request)

    if request.provider.lower() == "codex" and existing is not None and request.parent_session_id is not None and (
        existing.parent_session_id is not None and existing.parent_session_id != request.parent_session_id
    ):
        raise SessionIngestionConflict("session_parent_immutable", "The registered parent cannot be replaced.")
    if request.provider.lower() == "codex":
        await asyncio.to_thread(validate_native_provenance,
            request.session_id, request.project_id,
            request.parent_session_id or (existing.parent_session_id if existing is not None else None),
            _merge_metadata(existing.provider_metadata if existing is not None else None, request.provider_metadata),
            previous=existing.provider_metadata if existing is not None else None,
        )

    provider = request.provider
    model = request.model
    native_source = request.provider_metadata.get("transcript_path") or (
        (existing.provider_metadata or {}).get("transcript_path") if existing is not None else None
    )
    if request.agent_slug and not (request.provider.lower() == "codex" and native_source):
        resolved = await resolve_agent(request.agent_slug, db)
        provider = resolved.provider
        model = resolved.model

    merged_metadata = _merge_metadata(
        request.provider_metadata,
        {"cwd": request.cwd} if request.cwd else None,
    )
    if request.provider.lower() == "codex":
        # Native evidence and ingestion cursors are written only by transcript ingestion.
        merged_metadata.pop("model_evidence", None)
        merged_metadata.pop("transcript_ingestion", None)
        merged_metadata.pop("native_observation_namespace", None)
        if native_source:
            evidence = validated_native_model_evidence(existing.id, existing.provider_metadata) if existing is not None else None
            observed = evidence.observed_model if evidence else None
            model = f"codex/{observed}" if observed else "codex/unknown"
    base_path = resolve_scope_base_path(merged_metadata, request.cwd)

    if not is_existing or existing is None:
        session = _build_new_session(request, provider, model, merged_metadata, base_path)
        if request.provider.lower() == "codex" and native_source:
            session.models_used = []
        db.add(session)
        await db.commit()
        return session, SessionUpsertResult(session_id=session.id, created=True)

    _update_existing_session(existing, request, provider, model, merged_metadata, base_path)
    if request.provider.lower() == "codex" and native_source:
        existing.models_used = (
            [used for used in existing.models_used or [] if used != "codex/unknown"]
            if evidence is not None else []
        )
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
    if session.provider == "codex" or session.session_type == "pi":
        await lock_session_event_ingestion(db, session_id)
    await db.refresh(session, with_for_update=True)
    if session.provider == "codex":
        await _validate_project_id(session.project_id)
        await _validate_native_parent_project(db, session)
        await asyncio.to_thread(validate_native_provenance,
            session.id, session.project_id, session.parent_session_id,
            _merge_metadata(session.provider_metadata, request.provider_metadata),
            previous=session.provider_metadata,
        )
        request = request.model_copy(update={"provider_metadata": {
            key: value for key, value in request.provider_metadata.items()
            if key not in {"model_evidence", "transcript_ingestion", "native_observation_namespace"}
        }})
    _apply_heartbeat_update(session, request)
    await db.commit()
    return session, SessionHeartbeatResult(session_id=session.id, updated=True)


async def append_normalized_events(
    db: AsyncSession,
    session_id: str,
    request: AppendNormalizedEventsRequest,
    session: Session | None = None,
    *,
    commit: bool = True,
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
    # Decide before storing: the duplicate-event path rolls back, which expires
    # ``session`` and makes any later column read a sync lazy load.
    transcript_backed = _is_transcript_backed_session(_session_if_loaded(session))
    result: AppendNormalizedEventsResult
    if len(request.events) == 1:
        event = request.events[0]
        if event.turn is None and event.sequence is None:
            result = await _store_single_implicit_event(
                db, session_id, event, session, commit=commit,
            )
        else:
            result = await _store_events_general(
                db, session_id, request.events, session, commit=commit,
            )
    else:
        result = await _store_events_general(db, session_id, request.events, session, commit=commit)

    if transcript_backed:
        await _reconcile_transcript_session_models(
            db, session_id, session=_session_if_loaded(session),
        )
    return result


async def finalize_session(
    session_id: str,
    request: FinalizeSessionRequest | None = None,
) -> FinalizeSessionResult:
    """Finalize a session by extracting citations and summaries."""
    payload = request or FinalizeSessionRequest()
    result = await analyze_session(
        session_id=session_id,
        citation_prefixes=payload.citation_prefixes,
        summary_tags=payload.summary_tags,
        git_context=payload.git_context,
        branch=payload.branch,
        transcript_path=payload.transcript_path,
    )
    return FinalizeSessionResult(
        session_id=result.session_id,
        citations_found=result.citations_found,
        citations_credited=result.citations_credited,
        summary_stored=result.summary_stored,
    )


async def ingest_transcript_events(
    db: AsyncSession,
    session_id: str,
    request: TranscriptIngestRequest,
    session: Session | None = None,
    *,
    repair_projection: bool = False,
) -> TranscriptIngestResult:
    """Parse a provider transcript and append normalized events idempotently."""
    adapter = _adapter_for_provider(request.provider)
    if session is not None and session.id != session_id:
        raise SessionIngestionConflict(
            "session_identity_mismatch",
            "The supplied session does not match the transcript target.",
        )
    if session is not None:
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        registered_path = metadata.get("transcript_path")
        if isinstance(registered_path, str) and registered_path != request.transcript_path:
            raise SessionIngestionConflict(
                "transcript_source_mismatch",
                "The transcript path does not match the source registered for this session.",
            )
    if session is not None and request.provider.lower() != "codex":
        if session.provider == "codex":
            raise SessionIngestionConflict("transcript_provider_mismatch", "The registered provider is Codex.")
        await lock_session_event_ingestion(db, session_id)
        await db.refresh(session)
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        if metadata.get("transcript_path") not in {None, request.transcript_path}:
            raise SessionIngestionConflict("transcript_source_mismatch", "The registered transcript source changed.")
        retained = metadata.get("transcript_ingestion")
        retained = retained if isinstance(retained, dict) else {}
        canonical_checkpoint = retained.get("checkpoint")
        if isinstance(canonical_checkpoint, str):
            request = request.model_copy(update={"checkpoint": canonical_checkpoint})
    if request.provider.lower() == "codex":
        if session is None:
            session = (await db.execute(select(Session).where(Session.id == session_id).limit(1))).scalar_one_or_none()
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        if session.provider != "codex":
            raise SessionIngestionConflict("transcript_provider_mismatch", "The registered provider is not Codex.")
        await lock_session_event_ingestion(db, session_id)
        # The caller's ORM row/cursor may predate a concurrent native refresh.
        await db.refresh(session)
        await _validate_project_id(session.project_id)
        await _validate_native_parent_project(db, session)
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        await asyncio.to_thread(validate_native_provenance,
            session.id, session.project_id, session.parent_session_id, metadata,
            previous=metadata, transcript_path=request.transcript_path,
        )
        retained = metadata.get("transcript_ingestion")
        retained = retained if isinstance(retained, dict) else {}
        # Two consumers may refresh the same source. Ignore client cursor state;
        # use only the server-owned cursor, including when the client lags behind.
        canonical_checkpoint = retained.get("checkpoint")
        request = request.model_copy(update={
            "checkpoint": canonical_checkpoint if isinstance(canonical_checkpoint, str) else None,
        })
    session_ref = ProviderSessionRef(
        provider_session_id=session_id,
        source_id=request.transcript_path,
    )
    events, next_checkpoint = await adapter.read_new_events(
        session_ref, None if repair_projection else request.checkpoint,
    )
    repair_events = []
    if repair_projection:
        committed = _load_parse_checkpoint(request.checkpoint)
        full = _load_parse_checkpoint(next_checkpoint)
        # A native home remount can change st_dev without changing the file.
        # Repair only a complete, previously consumed source; never feed its
        # history through append or silently acknowledge an unconsumed tail.
        if (
            not next_checkpoint
            or not request.checkpoint
            or committed.legacy
            or (committed.inode, committed.line_offset, committed.byte_offset, committed.tail_digest)
            != (full.inode, full.line_offset, full.byte_offset, full.tail_digest)
        ):
            raise SessionIngestionConflict(
                "transcript_repair_source_mismatch",
                "Projection repair requires the complete transcript matching its committed cursor.",
            )
        repair_events, events = events, []
    source_health = await asyncio.to_thread(inspect_transcript_source, request.transcript_path, next_checkpoint)
    model_evidence = None
    native_model_state = {}
    if request.provider.lower() == "codex":
        native_model_state = _load_parse_checkpoint(next_checkpoint).codex_model_state
        parsed = native_model_state.get("evidence")
        if isinstance(parsed, dict):
            try:
                model_evidence = SessionModelEvidence.model_validate({
                    **parsed, "source_path": request.transcript_path,
                    "source_generation": source_health.source_generation,
                })
            except ValidationError as exc:
                raise SessionIngestionConflict("transcript_model_evidence_invalid", "Invalid native model evidence.") from exc
            if model_evidence.session_id != session_id:
                raise SessionIngestionConflict("transcript_model_evidence_identity_mismatch", "Native evidence belongs to another thread.")
    boundaries = await adapter.detect_boundaries(session_ref, request.checkpoint)
    suppressed_commands = 0
    if not repair_projection and request.provider.lower() == "codex" and session is not None and (session.provider_metadata or {}).get("native_observation_namespace"):
        from .native_observations import (
            exclude_projected_rollout_commands,
            prepare_rollout_source_generation,
        )

        await prepare_rollout_source_generation(db, session, events)
        original_count = len(events)
        events = await exclude_projected_rollout_commands(db, session, events)
        suppressed_commands = original_count - len(events)
    # Source identity deduplicates native records; their parser sequence must
    # never collide with independently stored hooks or live observations.
    if session is not None and (session.provider_metadata or {}).get("native_observation_namespace"):
        # Managed native authority already owns lifecycle records and reserves
        # the rollout's ordering for command reconciliation.
        events = [event for event in events if event.event_type not in {"native_lifecycle", "native_settings"}]
    else:
        events = [event.model_copy(update={"sequence": None}) if event.source_event_id else event for event in events]
    append_result = await append_normalized_events(
        db=db,
        session_id=session_id,
        request=AppendNormalizedEventsRequest(events=events),
        **({"session": session, "commit": False} if session is not None else {}),
    )
    if not repair_projection and request.provider.lower() == "codex" and session is not None and (session.provider_metadata or {}).get("native_observation_namespace"):
        from .native_observations import retain_rollout_commands

        await retain_rollout_commands(db, session, events)
    events_updated = 0
    events_deduplicated = 0
    repaired_ids: list[str] = []
    if repair_projection and session is not None:
        from .projection_repair import deduplicate_mount_aliases, repair_codex_projection

        assert next_checkpoint is not None
        if request.provider.lower() != "codex":
            events_deduplicated = await deduplicate_mount_aliases(db, session_id, repair_events)
        events_updated, repaired_ids, next_checkpoint = await repair_codex_projection(
            db, session, repair_events, next_checkpoint,
            include_messages=request.provider.lower() != "codex",
        )
        if repaired_ids:
            last_turn = await get_max_turn(db, session_id)
            append_result = append_result.model_copy(update={
                "last_turn": last_turn,
                "last_sequence": await get_max_sequence(db, session_id, last_turn),
            })
    await _reconcile_transcript_session_models(
        db, session_id, session=session,
    )
    if append_result.events_appended == 0:
        await _reconcile_transcript_session_scope(
            db, session_id, session=session,
            commit=session is None,
        )
    result = TranscriptIngestResult(
        session_id=session_id,
        provider=request.provider,
        transcript_path=request.transcript_path,
        events_appended=append_result.events_appended + len(repaired_ids),
        events_skipped=append_result.events_skipped + suppressed_commands,
        events_updated=events_updated,
        events_deduplicated=events_deduplicated,
        last_turn=append_result.last_turn,
        last_sequence=append_result.last_sequence,
        event_ids=append_result.event_ids + repaired_ids,
        next_checkpoint=next_checkpoint,
        boundaries=[boundary.boundary_type for boundary in boundaries],
        source_health=source_health,
        model_evidence=model_evidence,
    )
    if session is not None:
        metadata = dict(session.provider_metadata or {})
        metadata.setdefault("transcript_path", request.transcript_path)
        metadata["transcript_ingestion"] = {
            "provider": request.provider,
            "transcript_path": request.transcript_path,
            "checkpoint": next_checkpoint,
            "source_health": source_health.model_dump(mode="json"),
        }
        if request.provider.lower() == "codex":
            metadata["model_evidence"] = model_evidence.model_dump(mode="json") if model_evidence else None
            observed = model_evidence.observed_model if model_evidence else None
            session.model = f"codex/{observed}" if observed else "codex/unknown"
            session.models_used = [f"codex/{model}" for model in native_model_state.get("observed_models", [])]
        session.provider_metadata = metadata
        await db.commit()
    return result
