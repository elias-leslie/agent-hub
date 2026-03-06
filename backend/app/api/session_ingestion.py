"""Provider-agnostic session ingestion API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sessions import SessionResponse
from app.db import get_db
from app.services.session_helpers import build_session_response, get_session_or_404
from app.services.session_ingestion import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    SessionUpsertRequest,
    SessionUpsertResult,
    append_normalized_events,
    finalize_session,
    upsert_session,
)

router = APIRouter(prefix="/session-ingestion", tags=["session-ingestion"])


class SessionUpsertResponse(SessionUpsertResult):
    """Upsert response with the current session snapshot."""

    session: SessionResponse


@router.post("/sessions/upsert", response_model=SessionUpsertResponse)
async def upsert_session_endpoint(
    request: SessionUpsertRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionUpsertResponse:
    """Create or update a session using the canonical ingestion contract."""
    try:
        session, result = await upsert_session(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SessionUpsertResponse(
        session_id=result.session_id,
        created=result.created,
        session=build_session_response(session),
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
        await get_session_or_404(db, session_id)
        return await append_normalized_events(db, session_id, request)
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
