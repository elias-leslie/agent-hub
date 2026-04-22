"""Sessions API - CRUD operations for conversation sessions."""

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._session_request_identity import (
    enrich_session_heartbeat_request,
    enrich_session_upsert_request,
)
from app.api.schemas.sessions import (
    CloseSessionResponse,
    CreateSessionEventRequest,
    CreateSessionEventResponse,
    SessionCreate,
    SessionEventsResponse,
    SessionForkRequest,
    SessionForkResponse,
    SessionListResponse,
    SessionPromoteRequest,
    SessionPromoteResponse,
    SessionResponse,
)
from app.db import get_db
from app.services.session_helpers import (
    build_event_responses,
    build_session_list_items,
    close_session_if_active,
    fork_session_at_turn,
    get_session_or_404,
    get_session_with_events,
    list_sessions_with_stats,
    promote_session_branch,
    query_session_events,
    validate_promotion_eligibility,
)
from app.services.session_ingestion import (
    AppendNormalizedEventsRequest,
    NormalizedEvent,
    SessionHeartbeatRequest,
    SessionUpsertRequest,
    append_normalized_events,
    heartbeat_session,
    upsert_session,
)
from app.services.session_responses import (
    build_full_session_response,
    build_project_lane_session_ids,
)
from app.services.session_transforms import build_session_response

router = APIRouter()

# Re-export schemas for backward compatibility
__all__ = ["SessionForkRequest", "SessionForkResponse", "SessionPromoteRequest", "SessionPromoteResponse", "router"]


def _normalize_list_sessions_stats(
    result: Sequence[Any],
) -> tuple[
    list[Any],
    int,
    dict[str, int],
    dict[str, int],
    dict[str, dict[str, int]],
    dict[str, int],
    dict[str, int],
]:
    """Support additive session stats fields without breaking older mocks."""
    if len(result) < 5:
        raise ValueError("list_sessions_with_stats returned incomplete result")

    sessions = list(result[0])
    total = int(result[1])
    msg_counts = dict(result[2])
    event_counts = dict(result[3])
    token_stats = dict(result[4])
    child_counts = dict(result[5]) if len(result) > 5 else {}
    active_child_counts = dict(result[6]) if len(result) > 6 else {}
    return (
        sessions,
        total,
        msg_counts,
        event_counts,
        token_stats,
        child_counts,
        active_child_counts,
    )


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    request: SessionCreate,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Create session (idempotent - returns existing if session_id provided)."""
    if request.agent_slug:
        http_request.state.agent_slug = request.agent_slug
    session_request = enrich_session_upsert_request(
        SessionUpsertRequest(
            session_id=request.session_id,
            project_id=request.project_id,
            provider=request.provider,
            model=request.model,
            session_type=request.session_type,
            agent_slug=request.agent_slug,
            external_id=request.external_id,
            current_branch=request.current_branch,
            cwd=request.cwd,
            declared_scope_paths=request.declared_scope_paths,
            observed_read_paths=request.observed_read_paths,
            observed_write_paths=request.observed_write_paths,
            scope_confidence=request.scope_confidence,
            provider_metadata=request.provider_metadata,
        ),
        http_request,
    )
    try:
        session, _ = await upsert_session(
            db,
            session_request,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return build_session_response(session)


@router.post("/sessions/{session_id}/heartbeat", response_model=SessionResponse)
async def heartbeat_existing_session(
    session_id: str,
    request: SessionHeartbeatRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Update live session/process state for an existing session."""
    heartbeat_request = enrich_session_heartbeat_request(request, http_request)
    try:
        session, _ = await heartbeat_session(db, session_id, heartbeat_request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_session_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Get a session by ID with all events."""
    try:
        session = await get_session_with_events(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await build_full_session_response(db, session)


@router.get("/sessions/{session_id}/events", response_model=SessionEventsResponse)
async def get_session_events(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    event_type: Annotated[str | None, Query(description="Filter by event type")] = None,
    turn: Annotated[int | None, Query(description="Filter by turn number")] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500, description="Items per page")] = 100,
) -> SessionEventsResponse:
    """Get session events with filtering and pagination."""
    try:
        await get_session_or_404(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    events, total, max_turn = await query_session_events(
        db, session_id, event_type, turn, page, page_size
    )
    return SessionEventsResponse(
        session_id=session_id,
        events=build_event_responses(events),
        total=total,
        max_turn=max_turn,
    )


@router.post(
    "/sessions/{session_id}/events",
    response_model=CreateSessionEventResponse,
    status_code=201,
)
async def create_session_event(
    session_id: str,
    request: CreateSessionEventRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateSessionEventResponse:
    """Create a lightweight session event (for CC PostToolUse hook).

    Stores the event directly as a SessionEvent in PostgreSQL.
    Used by CC hooks to record Write/Edit/Bash tool executions.
    """
    try:
        session = await get_session_or_404(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    result = await append_normalized_events(
        db=db,
        session_id=session_id,
        request=AppendNormalizedEventsRequest(
            events=[
                NormalizedEvent(
                    event_type=request.event_type,
                    tool_name=request.tool_name,
                    tool_input=request.tool_input,
                    content=request.content,
                    tool_output=request.tool_output,
                    model_used=request.model_used,
                    agent_id=request.agent_id,
                )
            ]
        ),
        session=session,
    )

    return CreateSessionEventResponse(
        event_id=result.event_ids[0] if result.event_ids else "",
        session_id=session_id,
        sequence=result.last_sequence,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a session."""
    try:
        session = await get_session_or_404(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await db.delete(session)
    await db.commit()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str | None, Query(description="Filter by project")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    agent_slug: Annotated[str | None, Query(description="Filter by agent slug")] = None,
    parent_session_id: Annotated[str | None, Query(description="Filter by parent session")] = None,
    session_type: Annotated[str | None, Query(description="Filter by session type")] = None,
    external_id: Annotated[str | None, Query(description="Filter by linked external work item")] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> SessionListResponse:
    """List sessions with pagination and filtering."""
    raw_stats = await list_sessions_with_stats(
        db,
        project_id=project_id,
        status=status,
        agent_slug=agent_slug,
        session_type=session_type,
        page=page,
        page_size=page_size,
        parent_session_id=parent_session_id,
        external_id=external_id,
    )
    sessions, total, msg_counts, event_counts, token_stats, child_counts, active_child_counts = (
        _normalize_list_sessions_stats(raw_stats)
    )
    owner_session_ids, specialist_session_ids = await build_project_lane_session_ids(
        db,
        {session.project_id for session in sessions},
    )
    return SessionListResponse(
        sessions=build_session_list_items(
            sessions,
            msg_counts,
            token_stats,
            event_counts=event_counts,
            child_counts=child_counts,
            active_child_counts=active_child_counts,
            owner_session_ids=owner_session_ids,
            specialist_session_ids=specialist_session_ids,
        ),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/sessions/{session_id}/close", response_model=CloseSessionResponse)
async def close_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CloseSessionResponse:
    """Close session (idempotent)."""
    try:
        session = await get_session_or_404(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    status, message = await close_session_if_active(db, session)
    return CloseSessionResponse(id=session.id, status=status, message=message)


@router.post("/sessions/{session_id}/fork", response_model=SessionForkResponse, status_code=201)
async def fork_session(
    session_id: str,
    request: SessionForkRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionForkResponse:
    """Fork session at specific turn for A/B testing or exploration."""
    try:
        parent = await get_session_with_events(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    new_id, fork_point, msg_count = await fork_session_at_turn(
        db, parent, request.fork_at_turn
    )
    return SessionForkResponse(
        id=new_id,
        parent_session_id=parent.id,
        fork_point_turn=fork_point,
        message_count=msg_count,
        branch_status="active",
    )


@router.post("/sessions/{session_id}/promote", response_model=SessionPromoteResponse)
async def promote_session(
    session_id: str,
    request: SessionPromoteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionPromoteResponse:
    """Promote a branch as the winner."""
    try:
        session = await get_session_or_404(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    validate_promotion_eligibility(session)
    discarded_siblings, patches_applied = await promote_session_branch(
        db, session, request.discard_siblings
    )
    return SessionPromoteResponse(
        id=session.id,
        branch_status="promoted",
        discarded_siblings=discarded_siblings,
        patches_applied=patches_applied,
    )
