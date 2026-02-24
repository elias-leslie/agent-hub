"""Memory API - Observation Capture Endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.services.memory.observation_schema import ObservationRequest, ObservationResponse
from app.services.memory.service import MemoryScope

from .memory_dependencies import get_scope_params

router = APIRouter()


@router.post("/observations", response_model=ObservationResponse)
async def capture_observation_endpoint(
    request: ObservationRequest,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> ObservationResponse:
    """
    Capture an observation and store it as a memory episode.

    Observations from various sources (Claude Code, agent chat, tasks) are
    converted into episodes with appropriate ingestion profiles and privacy
    filtering. Content wrapped in <private> tags is redacted; <memory> tags
    are stripped to prevent recursive storage.
    """
    from app.services.memory.capture_handler import capture_observation

    scope, scope_id = scope_params
    try:
        return await capture_observation(request, scope, scope_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to capture observation: {e}",
        ) from e
