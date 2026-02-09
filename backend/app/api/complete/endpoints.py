"""Completion API endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
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


@router.post("/complete", response_model=CompletionResponse)
async def complete(
    request: CompletionRequest,
    http_request: Request,
    x_skip_cache: Annotated[str | None, Header(alias="X-Skip-Cache")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    skip_cache = bool(x_skip_cache and x_skip_cache.lower() == "true")
    return await orchestrate_completion(request, http_request, skip_cache, db)


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """Estimate tokens and cost before making a completion request."""
    return await handle_estimate(request)
