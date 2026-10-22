"""Provider-agnostic session ingestion API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._session_request_identity import (
    enrich_session_heartbeat_request,
    enrich_session_upsert_request,
)
from app.api.access_control_helpers import require_project_access
from app.api.schemas.sessions import SessionResponse
from app.db import get_db
from app.services.session_ingestion import (
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
    append_normalized_events,
    finalize_session,
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)
from app.services.session_ingestion.native_models import (
    NativeObservation,
    NativeObservationBatch,
    NativeObservationResult,
    NativeProtocolProfileRegistration,
    NativeQuarantineBatch,
    NativeQuarantineRegistration,
    NativeSourceReceipt,
    NativeSourceRegistration,
)
from app.services.session_ingestion.native_observations import (
    approval_subject,
    ingest_native_observations,
    ingest_native_quarantine,
    list_native_protocol_profiles,
    native_capture_status,
    native_evidence_summary,
    qualify_native_protocol_profile,
    register_native_quarantine,
    register_native_source,
)
from app.services.session_ingestion.service import SessionIngestionConflict
from app.services.session_operations import get_or_create_session
from app.services.session_queries import get_session_or_404

router = APIRouter(prefix="/session-ingestion", tags=["session-ingestion"])


@router.get("/sessions/{session_id}/turn-diagnostics")
async def turn_diagnostics_endpoint(
    session_id: str, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    event_limit: int = Query(default=5000, ge=1, le=20000),
) -> dict[str, Any]:
    from app.services.session_turn_diagnostics import native_turn_diagnostics

    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    metadata = session.provider_metadata or {}
    native_path = metadata.get("transcript_path")
    managed = metadata.get("native_observation_namespace")
    if managed and not isinstance(native_path, str):
        return {"session_id": session_id, "source": "unavailable", "denominator": 0,
                "categories": [], "turns": [], "reason": "No registered native transcript for managed turn comparison."}
    result = await native_turn_diagnostics(db, session_id, limit=limit, event_limit=event_limit,
                                           managed_transcript=native_path if managed else None)
    if not managed:
        result["source_health"] = (metadata.get("transcript_ingestion") or {}).get("source_health")
    return result


@router.get("/sessions/{session_id}/native-sources/{source_id}/issues")
async def native_issues_endpoint(
    session_id: str, source_id: str, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    after_position: int = Query(default=0, ge=0),
    after_id: str = Query(default="", max_length=64),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Conflict payloads remain retrievable through the durable evidence authority."""
    from sqlalchemy import and_, or_, select

    from app.models import NativeObservationIssue, NativeObservationSource

    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native payloads require the internal evidence owner.")
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id != session.id:
        raise HTTPException(status_code=404, detail="Native source not found.")
    rows = (await db.execute(select(NativeObservationIssue).where(NativeObservationIssue.source_id == source.id, or_(NativeObservationIssue.position > after_position, and_(NativeObservationIssue.position == after_position, NativeObservationIssue.id > after_id))).order_by(NativeObservationIssue.position, NativeObservationIssue.id).limit(limit))).scalars().all()
    return {"source_id": source.id, "issues": [{"id": row.id, "position": row.position, "code": row.code, "observation": row.observation} for row in rows], "next_position": rows[-1].position if rows else after_position, "next_id": rows[-1].id if rows else after_id}


@router.get("/sessions/{session_id}/native-capture")
async def native_capture_status_endpoint(
    session_id: str, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    return await native_capture_status(db, session)


@router.get("/sessions/{session_id}/native-sources/{source_id}/observations")
async def native_receipts_endpoint(
    session_id: str, source_id: str, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    after_position: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Internal evidence access, paginated; no native-runtime dependency."""
    from sqlalchemy import select

    from app.models import NativeObservationReceipt, NativeObservationSource

    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native payloads require the internal evidence owner.")
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id != session.id:
        raise HTTPException(status_code=404, detail="Native source not found.")
    rows = (await db.execute(select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == source.id, NativeObservationReceipt.position > after_position).order_by(NativeObservationReceipt.position).limit(limit))).scalars().all()
    receipts = []
    for row in rows:
        receipts.append({"position": row.position, "payload_hash": row.payload_hash, "observation": row.observation, "disposition": row.disposition, "issue_code": row.issue_code, "entity_id": row.entity_id, "normalized": row.normalized, "raw_pruned_at": row.raw_pruned_at.isoformat() if row.raw_pruned_at else None, "approval_subject": (row.normalized or {}).get("approval_subject") or await approval_subject(db, source.id, NativeObservation.model_validate(row.observation))})
    return {"source_id": source.id, "committed_position": source.committed_position, "receipts": receipts, "next_position": rows[-1].position if rows else after_position}


class SessionUpsertResponse(SessionUpsertResult):
    """Upsert response with the current session snapshot."""

    session: SessionResponse | None = None


class SessionHeartbeatResponse(SessionHeartbeatResult):
    """Heartbeat response with the current session snapshot."""

    session: SessionResponse | None = None


@router.post("/sessions/upsert", response_model=SessionUpsertResponse)
async def upsert_session_endpoint(
    request: SessionUpsertRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_session: Annotated[bool, Query(description="Include full session snapshot")] = True,
) -> SessionUpsertResponse:
    """Create or update a session using the canonical ingestion contract."""
    from app.services.session_helpers import build_session_response

    enriched_request = enrich_session_upsert_request(request, http_request)
    require_project_access(http_request, enriched_request.project_id)
    try:
        if not getattr(http_request.state, "is_internal", False):
            existing, is_existing = await get_or_create_session(db, enriched_request.session_id)
            if is_existing and existing is not None:
                require_project_access(http_request, existing.project_id)
                if existing.project_id != enriched_request.project_id:
                    raise SessionIngestionConflict(
                        "session_project_immutable",
                        "An existing session cannot be moved to another project.",
                    )
        session, result = await upsert_session(db, enriched_request)
    except SessionIngestionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    http_request.state.session_id = result.session_id  # request_logs attribution
    return SessionUpsertResponse(
        session_id=result.session_id,
        created=result.created,
        session=build_session_response(session) if include_session else None,
    )


@router.post(
    "/sessions/{session_id}/heartbeat",
    response_model=SessionHeartbeatResponse,
)
async def heartbeat_session_endpoint(
    session_id: str,
    request: SessionHeartbeatRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_session: Annotated[bool, Query(description="Include full session snapshot")] = True,
) -> SessionHeartbeatResponse:
    """Apply a canonical heartbeat update to an existing session."""
    from app.services.session_helpers import build_session_response

    enriched_request = enrich_session_heartbeat_request(request, http_request)
    try:
        if getattr(http_request.state, "is_internal", False):
            session, result = await heartbeat_session(db, session_id, enriched_request)
        else:
            session = await get_session_or_404(db, session_id)
            require_project_access(http_request, session.project_id)
            session, result = await heartbeat_session(
                db,
                session_id,
                enriched_request,
                session=session,
            )
    except SessionIngestionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionHeartbeatResponse(
        session_id=result.session_id,
        updated=result.updated,
        session=build_session_response(session) if include_session else None,
    )


@router.post(
    "/sessions/{session_id}/events/append",
    response_model=AppendNormalizedEventsResult,
)
async def append_events_endpoint(
    session_id: str,
    request: AppendNormalizedEventsRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AppendNormalizedEventsResult:
    """Append normalized events to an existing session."""
    try:
        session = await get_session_or_404(db, session_id)
        require_project_access(http_request, session.project_id)
        return await append_normalized_events(db, session_id, request, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/finalize",
    response_model=FinalizeSessionResult,
)
async def finalize_session_endpoint(
    session_id: str,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: FinalizeSessionRequest | None = None,
) -> FinalizeSessionResult:
    """Finalize a session by extracting citations, feedback, and summaries."""
    if not getattr(http_request.state, "is_internal", False):
        try:
            session = await get_session_or_404(db, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        require_project_access(http_request, session.project_id)

    try:
        return await finalize_session(session_id, request)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to finalize session: {exc}",
        ) from exc


@router.post(
    "/sessions/{session_id}/transcript-events",
    response_model=TranscriptIngestResult,
)
async def ingest_transcript_events_endpoint(
    session_id: str,
    request: TranscriptIngestRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TranscriptIngestResult:
    """Translate a provider transcript into normalized session events."""
    try:
        session = await get_session_or_404(db, session_id)
        require_project_access(http_request, session.project_id)
        return await ingest_transcript_events(db, session_id, request, session=session)
    except SessionIngestionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/transcript-refresh",
    response_model=TranscriptIngestResult,
)
async def refresh_transcript_events_endpoint(
    session_id: str,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    repair_projection: Annotated[
        bool, Query(description="Recover missing native events and repair known instruction roles"),
    ] = False,
) -> TranscriptIngestResult:
    """Catch up the exact transcript source already registered for a session."""
    try:
        session = await get_session_or_404(db, session_id)
        require_project_access(http_request, session.project_id)
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
        retained = metadata.get("transcript_ingestion")
        retained = retained if isinstance(retained, dict) else {}
        transcript_path = metadata.get("transcript_path")
        if not isinstance(transcript_path, str) or not transcript_path:
            raise SessionIngestionConflict(
                "transcript_source_unregistered",
                "This session has no registered native transcript source.",
            )
        provider = retained.get("provider") or session.provider
        if not isinstance(provider, str) or not provider:
            raise SessionIngestionConflict(
                "transcript_provider_unregistered",
                "This session has no registered transcript provider.",
            )
        checkpoint = retained.get("checkpoint")
        if checkpoint is not None and not isinstance(checkpoint, str):
            raise SessionIngestionConflict(
                "transcript_checkpoint_invalid",
                "The retained transcript checkpoint is invalid.",
            )
        return await ingest_transcript_events(
            db,
            session_id,
            TranscriptIngestRequest(
                provider=provider,
                transcript_path=transcript_path,
                checkpoint=checkpoint,
            ),
            session=session,
            **({"repair_projection": True} if repair_projection else {}),
        )
    except SessionIngestionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/native-sources")
async def register_native_source_endpoint(
    session_id: str, request: NativeSourceRegistration, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NativeSourceReceipt:
    """Register an execution-owner attested source without granting execution control."""
    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native sources require the internal execution owner.")
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    try:
        return await register_native_source(db, session, request)
    except SessionIngestionConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/sessions/{session_id}/native-sources/{source_id}/observations")
async def ingest_native_observations_endpoint(
    session_id: str, source_id: str, request: NativeObservationBatch, http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NativeObservationResult:
    """Commit shadow receipts; App Server observations never append timeline commands."""
    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native observations require the internal execution owner.")
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    try:
        return await ingest_native_observations(db, session, source_id, request)
    except SessionIngestionConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/native-quarantine")
async def register_native_quarantine_endpoint(request: NativeQuarantineRegistration, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> NativeSourceReceipt:
    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native quarantine requires the internal evidence owner.")
    require_project_access(http_request, request.project_id)
    try:
        return await register_native_quarantine(db, request)
    except SessionIngestionConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc

    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown quarantine project.") from exc

@router.post("/native-quarantine/{source_id}/observations")
async def ingest_native_quarantine_endpoint(source_id: str, request: NativeQuarantineBatch, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> NativeObservationResult:
    from app.models import NativeObservationSource

    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native quarantine requires the internal evidence owner.")
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id is not None or not source.project_id:
        raise HTTPException(status_code=404, detail="Quarantine source not found.")
    require_project_access(http_request, source.project_id)
    try:
        return await ingest_native_quarantine(db, source, request)
    except SessionIngestionConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/native-quarantine")
async def native_quarantine_health_endpoint(project_id: str, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.models import NativeObservationReceipt, NativeObservationSource

    require_project_access(http_request, project_id)
    rows = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id.is_(None), NativeObservationSource.project_id == project_id))).scalars().all()
    sources = []
    for source in rows:
        count, maximum, latest = (await db.execute(select(func.count(), func.max(NativeObservationReceipt.position), func.max(NativeObservationReceipt.received_at)).where(NativeObservationReceipt.source_id == source.id))).one()
        sources.append({"source_id": source.id, "committed_position": source.committed_position, "receipt_count": count, "max_position": maximum or 0, "last_received_at": latest.isoformat() if latest else None})
    return {"schema_version": "native-observation.v1", "project_id": project_id, "subject_binding": "unbound", "sources": sources}


@router.get("/native-quarantine/{source_id}/observations")
async def native_quarantine_receipts_endpoint(source_id: str, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)], after_position: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models import NativeObservationReceipt, NativeObservationSource

    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native payloads require the internal evidence owner.")
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id is not None or not source.project_id:
        raise HTTPException(status_code=404, detail="Quarantine source not found.")
    require_project_access(http_request, source.project_id)
    rows = (await db.execute(select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == source_id, NativeObservationReceipt.position > after_position).order_by(NativeObservationReceipt.position).limit(limit))).scalars().all()
    return {"source_id": source.id, "committed_position": source.committed_position, "receipts": [{"position": row.position, "payload_hash": row.payload_hash, "observation": row.observation, "disposition": row.disposition, "issue_code": row.issue_code} for row in rows], "next_position": rows[-1].position if rows else after_position}


@router.get("/sessions/{session_id}/native-evidence-summary")
async def native_evidence_summary_endpoint(session_id: str, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)], after_entity_id: str = Query(default="", max_length=64), limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    session = await get_session_or_404(db, session_id)
    require_project_access(http_request, session.project_id)
    return await native_evidence_summary(db, session, after_entity_id=after_entity_id, limit=limit)


@router.get("/native-quarantine/{source_id}/issues")
async def native_quarantine_issues_endpoint(source_id: str, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)], after_position: int = Query(default=0, ge=0), after_id: str = Query(default="", max_length=64), limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    from sqlalchemy import and_, or_, select

    from app.models import NativeObservationIssue, NativeObservationSource

    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Native payloads require the internal evidence owner.")
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id is not None or not source.project_id:
        raise HTTPException(status_code=404, detail="Quarantine source not found.")
    require_project_access(http_request, source.project_id)
    rows = (await db.execute(select(NativeObservationIssue).where(NativeObservationIssue.source_id == source.id, or_(NativeObservationIssue.position > after_position, and_(NativeObservationIssue.position == after_position, NativeObservationIssue.id > after_id))).order_by(NativeObservationIssue.position, NativeObservationIssue.id).limit(limit))).scalars().all()
    return {"source_id": source.id, "issues": [{"id": row.id, "position": row.position, "code": row.code, "observation": row.observation} for row in rows], "next_position": rows[-1].position if rows else after_position, "next_id": rows[-1].id if rows else after_id}


@router.post("/native-protocol-profiles")
async def qualify_native_protocol_profile_endpoint(request: NativeProtocolProfileRegistration, http_request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Protocol qualification requires the internal evidence owner.")
    try:
        return await qualify_native_protocol_profile(db, request)
    except SessionIngestionConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/native-protocol-profiles")
async def native_protocol_profiles_endpoint(http_request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    if not getattr(http_request.state, "is_internal", False):
        raise HTTPException(status_code=403, detail="Protocol profiles require the internal evidence owner.")
    return await list_native_protocol_profiles(db)
