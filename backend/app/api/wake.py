"""Wake API — fire-and-forget agent invocations.

Projects POST context here to wake an agent (e.g., Johnny) for event-driven
responses like task failures, quality gate failures, or autocode completions.
The completion runs asynchronously via Hatchet.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wake", tags=["wake"])


class WakeRequest(BaseModel):
    """Request to wake an agent with context."""

    agent_slug: str = Field(description="Agent to wake (e.g., 'johnny')")
    context: str = Field(description="Context message for the agent")
    project_id: str = Field(default="summitflow", description="Source project")
    event_type: str = Field(
        default="generic", description="Event type: task_failure, quality_gate, autocode_complete, generic"
    )
    task_id: str | None = Field(default=None, description="Related task ID (if any)")


class WakeResponse(BaseModel):
    status: str = "dispatched"
    message: str = ""


@router.post("", response_model=WakeResponse)
async def wake_agent(request: WakeRequest, db: AsyncSession = Depends(get_db)) -> WakeResponse:
    """Wake an agent with context. Runs completion asynchronously."""
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, request.agent_slug)
    if not agent:
        return WakeResponse(status="error", message=f"Agent '{request.agent_slug}' not found")

    model = agent.primary_model_id
    provider = get_provider_for_model(model)

    # Build contextual prompt
    prompt = f"[Wake: {request.event_type}] {request.context}"
    if request.task_id:
        prompt += f"\n\nRelated task: {request.task_id}"

    # Dispatch via Hatchet for async execution
    from app.workflows.johnny_wake import dispatch_wake

    dispatch_wake(
        agent_slug=request.agent_slug,
        model=model,
        provider=provider,
        temperature=agent.temperature,
        prompt=prompt,
        project_id=request.project_id,
        event_type=request.event_type,
        thinking_level=agent.thinking_level,
    )

    logger.info(
        "Wake dispatched: agent=%s event=%s project=%s",
        request.agent_slug,
        request.event_type,
        request.project_id,
    )
    return WakeResponse(
        status="dispatched",
        message=f"Agent '{request.agent_slug}' wake dispatched for {request.event_type}",
    )
