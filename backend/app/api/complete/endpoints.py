"""Completion API endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.complete_orchestrator import orchestrate_completion
from app.api.complete.estimate_endpoint import handle_estimate
from app.api.complete.schemas import (
    CompletionRequest,
    CompletionResponse,
    EstimateRequest,
    EstimateResponse,
)
from app.db import get_db

router = APIRouter()


class CancelStreamRequest(BaseModel):
    """Request to cancel an active streaming completion."""

    session_id: str = Field(..., description="Session ID of the stream to cancel")


@router.post("/complete", response_model=CompletionResponse)
async def complete(
    request: CompletionRequest,
    http_request: Request,
    x_skip_cache: Annotated[str | None, Header(alias="X-Skip-Cache")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Generate a completion for the given messages.

    Routes to the appropriate workload provider based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    # Set early so request telemetry includes agent attribution even for early failures.
    http_request.state.agent_slug = request.agent_slug
    skip_cache = bool(x_skip_cache and x_skip_cache.lower() == "true")
    return await orchestrate_completion(request, http_request, skip_cache, db)


@router.post("/complete/cancel")
async def cancel_stream(request: CancelStreamRequest) -> dict[str, object]:
    """Cancel an active streaming completion.

    Signals the backend to stop executing remaining tools after the current
    tool completes. Used by frontends when the user sends a new message
    during tool execution (steering) or explicitly cancels.
    """
    from app.api.complete.streaming_context import StreamContext

    cancelled = StreamContext.cancel(request.session_id)
    return {"cancelled": cancelled, "session_id": request.session_id}


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """Estimate tokens and cost before making a completion request."""
    return await handle_estimate(request)
