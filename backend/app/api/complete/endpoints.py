"""Completion API endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
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
    NativeContinuationCloseRequest,
    NativeContinuationReceiptResponse,
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


@router.post("/complete/native/close")
async def close_native_session(
    request: NativeContinuationCloseRequest,
    http_request: Request,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> dict[str, object]:
    """Close one exact retained native generation without running another turn."""
    from app.api.complete.native_continuation import close_native_continuation

    return await close_native_continuation(
        session_id=request.session_id,
        generation=request.generation,
        controller_generation=request.controller_generation,
        client_id=getattr(http_request.state, "client_id", None),
        db=db,
    )


@router.get("/complete/native/receipt", response_model=NativeContinuationReceiptResponse)
async def native_receipt(
    http_request: Request,
    response: Response,
    session_id: Annotated[str, Query(min_length=1, max_length=100)],
    project_id: Annotated[str, Query(min_length=1, max_length=100)],
    generation: Annotated[int, Query(ge=1)],
    request_id: Annotated[str, Query(min_length=1, max_length=100)],
    controller_generation: Annotated[str, Query(min_length=1, max_length=100)],
    expected_turn: Annotated[int | None, Query(ge=0)] = None,
    context_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    payload_hash: Annotated[str | None, Query(pattern="^[a-f0-9]{64}$")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> NativeContinuationReceiptResponse:
    """Inspect a saved turn without provider, generation, or transcript side effects."""
    from app.api.complete.native_continuation import lookup_native_receipt
    from app.middleware.access_control_auth import require_service_client
    from app.models.client import check_project_access

    response.headers["Cache-Control"] = "no-store"
    client = await require_service_client(http_request)
    if not check_project_access(client.get("allowed_projects", "[]"), project_id):
        raise HTTPException(status_code=403, detail="Project not allowed.")
    return await lookup_native_receipt(
        session_id=session_id,
        project_id=project_id,
        generation=generation,
        request_id=request_id,
        controller_generation=controller_generation,
        expected_turn=expected_turn,
        context_version=context_version,
        payload_hash=payload_hash,
        client_id=client["id"],
        db=db,
    )


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """Estimate tokens and cost before making a completion request."""
    return await handle_estimate(request)
