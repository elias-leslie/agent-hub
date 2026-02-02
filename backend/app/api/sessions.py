"""Sessions API - CRUD operations for conversation sessions."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.sessions import (
    CloseSessionResponse,
    ContextUsageResponse,
    SessionCreate,
    SessionForkRequest,
    SessionForkResponse,
    SessionListResponse,
    SessionPromoteRequest,
    SessionPromoteResponse,
    SessionResponse,
)
from app.db import get_db
from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.context_tracker import calculate_context_usage
from app.services.events import publish_session_start
from app.services.session_helpers import (
    apply_session_filters,
    build_session_list_items,
    build_session_response,
    calculate_agent_token_breakdown,
    convert_messages_to_response,
    copy_messages_to_forked_session,
    create_forked_session,
    discard_sibling_sessions,
    fetch_session_statistics,
    prepare_fork_data,
    validate_promotion_eligibility,
)

router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    request: SessionCreate,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Create a new conversation session."""
    session_id = str(uuid.uuid4())

    # Resolve agent if agent_slug is provided
    provider = request.provider
    model = request.model
    if request.agent_slug:
        resolved = await resolve_agent(request.agent_slug, db)
        provider = resolved.provider
        model = resolved.model
        # Set agent_slug on request.state for access control middleware logging
        http_request.state.agent_slug = request.agent_slug

    session = Session(
        id=session_id,
        project_id=request.project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=request.session_type,
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Publish session_start event
    await publish_session_start(session_id, request.model, request.project_id)

    return build_session_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Get a session by ID with all messages."""
    result = await db.execute(
        select(Session).options(selectinload(Session.messages)).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Calculate context usage
    ctx_usage = await calculate_context_usage(db, session_id, session.model)
    context_usage_response = ContextUsageResponse(
        used_tokens=ctx_usage.used_tokens,
        limit_tokens=ctx_usage.limit_tokens,
        percent_used=ctx_usage.percent_used,
        remaining_tokens=ctx_usage.remaining_tokens,
        warning=ctx_usage.warning,
    )

    # Calculate agent token breakdown for multi-agent sessions
    agent_breakdown, total_input, total_output = calculate_agent_token_breakdown(session.messages)

    return build_session_response(
        session,
        convert_messages_to_response(session.messages),
        context_usage_response,
        agent_breakdown,
        total_input,
        total_output,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete/archive a session."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark as completed rather than hard delete
    session.status = "completed"
    await db.commit()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str | None, Query(description="Filter by project")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    agent_slug: Annotated[str | None, Query(description="Filter by agent slug")] = None,
    session_type: Annotated[str | None, Query(description="Filter by session type")] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> SessionListResponse:
    """List sessions with pagination and filtering."""
    # Build and filter queries
    query, count_query = apply_session_filters(
        select(Session),
        select(func.count(Session.id)),
        project_id,
        status,
        agent_slug,
        session_type,
    )

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    sessions = list(result.scalars().all())

    # Fetch statistics
    session_ids = [s.id for s in sessions]
    msg_counts, token_stats = await fetch_session_statistics(db, session_ids)

    return SessionListResponse(
        sessions=build_session_list_items(sessions, msg_counts, token_stats),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/sessions/{session_id}/close", response_model=CloseSessionResponse)
async def close_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CloseSessionResponse:
    """Explicitly close a session.

    Marks the session as completed. Use this for clean session termination.
    This is idempotent - calling on an already-completed session is safe.
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "completed":
        return CloseSessionResponse(
            id=session.id,
            status="completed",
            message="Session was already completed",
        )

    session.status = "completed"
    await db.commit()

    return CloseSessionResponse(
        id=session.id,
        status="completed",
        message="Session closed successfully",
    )


@router.post("/sessions/{session_id}/fork", response_model=SessionForkResponse, status_code=201)
async def fork_session(
    session_id: str,
    request: SessionForkRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionForkResponse:
    """Fork a session at a specific turn for A/B testing or exploration.

    Creates a new session with:
    - All messages up to fork_at_turn copied
    - parent_session_id set to the original session
    - fork_point_turn set to the fork point
    - branch_status set to "active"

    Use cases:
    - A/B testing different approaches
    - Exploring alternative paths
    - Recovery from mistakes
    - 3-2-1 escalation (parallel attempts)
    """
    result = await db.execute(
        select(Session).options(selectinload(Session.messages)).where(Session.id == session_id)
    )
    parent = result.scalar_one_or_none()

    if not parent:
        raise HTTPException(status_code=404, detail="Session not found")

    sorted_messages = sorted(parent.messages, key=lambda x: x.created_at)
    messages_to_copy, fork_at = prepare_fork_data(sorted_messages, request.fork_at_turn)

    new_session_id = str(uuid.uuid4())
    forked_session = create_forked_session(parent, new_session_id, fork_at)
    db.add(forked_session)
    copy_messages_to_forked_session(db, messages_to_copy, new_session_id)
    await db.commit()

    return SessionForkResponse(
        id=new_session_id,
        parent_session_id=parent.id,
        fork_point_turn=fork_at,
        message_count=len(messages_to_copy),
        branch_status="active",
    )


@router.post("/sessions/{session_id}/promote", response_model=SessionPromoteResponse)
async def promote_session(
    session_id: str,
    request: SessionPromoteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionPromoteResponse:
    """Promote a branch as the winner."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    validate_promotion_eligibility(session)
    assert session.parent_session_id is not None  # Validated above

    # Discard sibling branches if requested
    discarded_siblings = (
        await discard_sibling_sessions(db, session.parent_session_id, session_id)
        if request.discard_siblings
        else []
    )

    session.branch_status = "promoted"
    session.manual_outcome = "selected"

    patches_applied = 0
    if session.pending_patches:
        patches_applied = len(session.pending_patches)
        session.pending_patches = None

    await db.commit()

    return SessionPromoteResponse(
        id=session.id,
        branch_status="promoted",
        discarded_siblings=discarded_siblings,
        patches_applied=patches_applied,
    )
