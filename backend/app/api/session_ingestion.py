"""Provider-agnostic session ingestion API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._session_request_identity import (
    enrich_session_heartbeat_request,
    enrich_session_upsert_request,
)
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
from app.services.session_queries import get_session_or_404

router = APIRouter(prefix="/session-ingestion", tags=["session-ingestion"])


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
    try:
        session, result = await upsert_session(db, enriched_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        session, result = await heartbeat_session(db, session_id, enriched_request)
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
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AppendNormalizedEventsResult:
    """Append normalized events to an existing session."""
    try:
        session = await get_session_or_404(db, session_id)
        return await append_normalized_events(db, session_id, request, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/finalize",
    response_model=FinalizeSessionResult,
)
async def finalize_session_endpoint(
    session_id: str,
    request: FinalizeSessionRequest | None = None,
) -> FinalizeSessionResult:
    """Finalize a session by extracting citations, feedback, and summaries."""
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
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TranscriptIngestResult:
    """Translate a provider transcript into normalized session events."""
    try:
        await get_session_or_404(db, session_id)
        return await ingest_transcript_events(db, session_id, request)
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
