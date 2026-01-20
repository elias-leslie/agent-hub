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
from app.services.events import publish_session_start
from app.services.stream_registry import get_stream_registry

router = APIRouter()


# Request/Response schemas
class SessionCreate(BaseModel):
    """Request body for creating a session."""

    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")
    session_type: str = Field(
        default="completion",
        description="Session type: completion, chat, roundtable, image_generation, agent",
    )


class MessageResponse(BaseModel):
    """Message within a session."""

    id: int
    role: str
    content: str
    tokens: int | None
    agent_id: str | None = Field(
        default=None, description="Agent identifier for multi-agent sessions"
    )
    agent_name: str | None = Field(default=None, description="Agent display name")
    created_at: datetime


class AgentTokenBreakdown(BaseModel):
    """Token breakdown for a single agent in multi-agent sessions."""

    agent_id: str
    agent_name: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    message_count: int


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
    purpose: str | None = Field(default=None, description="Session purpose")
    session_type: str = Field(default="completion", description="Session type")
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)
    context_usage: ContextUsageResponse | None = Field(
        default=None, description="Context window usage"
    )
    agent_token_breakdown: list[AgentTokenBreakdown] = Field(
        default_factory=list, description="Token breakdown by agent for multi-agent sessions"
    )
    total_input_tokens: int = Field(default=0, description="Total input tokens")
    total_output_tokens: int = Field(default=0, description="Total output tokens")


class SessionListItem(BaseModel):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    purpose: str | None = Field(default=None, description="Session purpose")
    session_type: str = Field(default="completion", description="Session type")
    message_count: int
    total_input_tokens: int = Field(default=0, description="Total input tokens")
    total_output_tokens: int = Field(default=0, description="Total output tokens")
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
        session_type=request.session_type,
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Publish session_start event
    await publish_session_start(session_id, request.model, request.project_id)

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=session.provider,
        model=session.model,
        status=session.status,
        purpose=session.purpose,
        session_type=session.session_type or "completion",
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
    agent_breakdown: list[AgentTokenBreakdown] = []
    total_input = 0
    total_output = 0

    # Group messages by agent_id
    agent_stats: dict[str, dict] = {}
    for m in session.messages:
        agent_key = m.agent_id or "_default"
        if agent_key not in agent_stats:
            agent_stats[agent_key] = {
                "agent_id": m.agent_id or "default",
                "agent_name": m.agent_name,
                "input_tokens": 0,
                "output_tokens": 0,
                "message_count": 0,
            }
        tokens = m.tokens or 0
        if m.role == "user":
            agent_stats[agent_key]["input_tokens"] += tokens
            total_input += tokens
        else:
            agent_stats[agent_key]["output_tokens"] += tokens
            total_output += tokens
        agent_stats[agent_key]["message_count"] += 1

    # Build breakdown list (only if multiple agents or explicit agent_id)
    for stats in agent_stats.values():
        if stats["agent_id"] != "default" or len(agent_stats) > 1:
            agent_breakdown.append(
                AgentTokenBreakdown(
                    agent_id=stats["agent_id"],
                    agent_name=stats["agent_name"],
                    input_tokens=stats["input_tokens"],
                    output_tokens=stats["output_tokens"],
                    total_tokens=stats["input_tokens"] + stats["output_tokens"],
                    message_count=stats["message_count"],
                )
            )

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=session.provider,
        model=session.model,
        status=session.status,
        purpose=session.purpose,
        session_type=session.session_type or "completion",
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                tokens=m.tokens,
                agent_id=m.agent_id,
                agent_name=m.agent_name,
                created_at=m.created_at,
            )
            for m in sorted(session.messages, key=lambda x: x.created_at)
        ],
        context_usage=context_usage_response,
        agent_token_breakdown=agent_breakdown,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
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
    purpose: Annotated[str | None, Query(description="Filter by purpose")] = None,
    session_type: Annotated[str | None, Query(description="Filter by session type")] = None,
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
    if purpose:
        query = query.where(Session.purpose == purpose)
        count_query = count_query.where(Session.purpose == purpose)
    if session_type:
        query = query.where(Session.session_type == session_type)
        count_query = count_query.where(Session.session_type == session_type)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    sessions = result.scalars().all()

    # Get message counts and token sums for each session
    session_ids = [s.id for s in sessions]
    msg_counts: dict[str, int] = {}
    token_stats: dict[str, dict[str, int]] = {}

    if session_ids:
        # Message counts
        msg_counts_result = await db.execute(
            select(Message.session_id, func.count(Message.id))
            .where(Message.session_id.in_(session_ids))
            .group_by(Message.session_id)
        )
        msg_counts = dict(msg_counts_result.all())

        # Token sums by role (input = user messages, output = assistant messages)
        token_result = await db.execute(
            select(
                Message.session_id,
                Message.role,
                func.coalesce(func.sum(Message.tokens), 0),
            )
            .where(Message.session_id.in_(session_ids))
            .group_by(Message.session_id, Message.role)
        )
        for session_id, role, tokens in token_result.all():
            if session_id not in token_stats:
                token_stats[session_id] = {"input": 0, "output": 0}
            if role == "user":
                token_stats[session_id]["input"] = tokens
            elif role == "assistant":
                token_stats[session_id]["output"] = tokens

    return SessionListResponse(
        sessions=[
            SessionListItem(
                id=s.id,
                project_id=s.project_id,
                provider=s.provider,
                model=s.model,
                status=s.status,
                purpose=s.purpose,
                session_type=s.session_type or "completion",
                message_count=msg_counts.get(s.id, 0),
                total_input_tokens=token_stats.get(s.id, {}).get("input", 0),
                total_output_tokens=token_stats.get(s.id, {}).get("output", 0),
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


class CloseSessionResponse(BaseModel):
    """Response body for session close."""

    id: str = Field(..., description="Session ID")
    status: str = Field(..., description="New session status")
    message: str = Field(..., description="Status message")


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
