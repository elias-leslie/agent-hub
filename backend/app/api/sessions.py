"""Sessions API - CRUD operations for conversation sessions."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Message, Session
from app.services.context_tracker import calculate_context_usage
from app.services.stream_registry import get_stream_registry

router = APIRouter()


# Request/Response schemas
class SessionCreate(BaseModel):
    """Request body for creating a session."""

    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")


class MessageResponse(BaseModel):
    """Message within a session."""

    id: int
    role: str
    content: str
    tokens: int | None
    created_at: datetime


class ContextUsageResponse(BaseModel):
    """Context window usage for a session."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(default=None, description="Warning if approaching limit")


class SessionResponse(BaseModel):
    """Response body for session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)
    context_usage: ContextUsageResponse | None = Field(default=None, description="Context window usage")


class SessionListItem(BaseModel):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response body for listing sessions."""

    sessions: list[SessionListItem]
    total: int
    page: int
    page_size: int


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    request: SessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Create a new conversation session."""
    session_id = str(uuid.uuid4())

    session = Session(
        id=session_id,
        project_id=request.project_id,
        provider=request.provider,
        model=request.model,
        status="active",
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=session.provider,
        model=session.model,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[],
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    """Get a session by ID with all messages."""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.messages))
        .where(Session.id == session_id)
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

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=session.provider,
        model=session.model,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                tokens=m.tokens,
                created_at=m.created_at,
            )
            for m in sorted(session.messages, key=lambda x: x.created_at)
        ],
        context_usage=context_usage_response,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete/archive a session."""
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
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
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> SessionListResponse:
    """List sessions with pagination and filtering."""
    # Build base query
    query = select(Session)
    count_query = select(func.count(Session.id))

    # Apply filters
    if project_id:
        query = query.where(Session.project_id == project_id)
        count_query = count_query.where(Session.project_id == project_id)
    if status:
        query = query.where(Session.status == status)
        count_query = count_query.where(Session.status == status)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    sessions = result.scalars().all()

    # Get message counts for each session
    session_ids = [s.id for s in sessions]
    if session_ids:
        msg_counts_result = await db.execute(
            select(Message.session_id, func.count(Message.id))
            .where(Message.session_id.in_(session_ids))
            .group_by(Message.session_id)
        )
        msg_counts = dict(msg_counts_result.all())
    else:
        msg_counts = {}

    return SessionListResponse(
        sessions=[
            SessionListItem(
                id=s.id,
                project_id=s.project_id,
                provider=s.provider,
                model=s.model,
                status=s.status,
                message_count=msg_counts.get(s.id, 0),
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


class CancelStreamResponse(BaseModel):
    """Response body for stream cancellation."""

    session_id: str = Field(..., description="Session ID that was cancelled")
    cancelled: bool = Field(..., description="Whether cancellation was successful")
    input_tokens: int = Field(default=0, description="Input tokens used before cancel")
    output_tokens: int = Field(default=0, description="Output tokens generated before cancel")
    message: str = Field(..., description="Status message")


@router.post("/sessions/{session_id}/cancel", response_model=CancelStreamResponse)
async def cancel_stream(session_id: str) -> CancelStreamResponse:
    """
    Cancel an active streaming session.

    Returns 409 if no active stream is found for this session.

    This endpoint allows REST-based cancellation of WebSocket streams,
    useful for scenarios where the client has lost WebSocket connection
    but can still make HTTP requests.
    """
    registry = get_stream_registry()

    # Check if there's an active stream for this session
    stream_state = await registry.get_stream(session_id)

    if not stream_state:
        raise HTTPException(
            status_code=409,
            detail="No active stream for this session",
        )

    if stream_state.cancelled:
        # Already cancelled
        return CancelStreamResponse(
            session_id=session_id,
            cancelled=True,
            input_tokens=stream_state.input_tokens,
            output_tokens=stream_state.output_tokens,
            message="Stream was already cancelled",
        )

    # Request cancellation
    updated_state = await registry.cancel_stream(session_id)

    if not updated_state:
        raise HTTPException(
            status_code=409,
            detail="Failed to cancel stream",
        )

    return CancelStreamResponse(
        session_id=session_id,
        cancelled=True,
        input_tokens=updated_state.input_tokens,
        output_tokens=updated_state.output_tokens,
        message="Stream cancellation requested",
    )
