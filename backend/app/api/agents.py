"""Agent management API endpoints.

CRUD operations for managing agent configurations.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.agent_service import AgentDTO, get_agent_service
from app.services.api_key_auth import AuthenticatedKey, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# Request/Response schemas
class AgentCreateRequest(BaseModel):
    """Request schema for creating an agent."""

    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    system_prompt: str = Field(..., min_length=1)
    primary_model_id: str = Field(..., min_length=1)
    fallback_models: list[str] = Field(default_factory=list)
    escalation_model_id: str | None = None
    strategies: dict[str, Any] = Field(default_factory=dict)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    is_active: bool = True


class AgentUpdateRequest(BaseModel):
    """Request schema for updating an agent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    primary_model_id: str | None = Field(default=None, min_length=1)
    fallback_models: list[str] | None = None
    escalation_model_id: str | None = None
    strategies: dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    is_active: bool | None = None
    change_reason: str | None = None


class AgentResponse(BaseModel):
    """Response schema for agent data."""

    id: int
    slug: str
    name: str
    description: str | None
    system_prompt: str
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    strategies: dict[str, Any]
    temperature: float
    is_active: bool
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_dto(cls, dto: AgentDTO) -> "AgentResponse":
        """Create response from DTO."""
        return cls(
            id=dto.id,
            slug=dto.slug,
            name=dto.name,
            description=dto.description,
            system_prompt=dto.system_prompt,
            primary_model_id=dto.primary_model_id,
            fallback_models=dto.fallback_models,
            escalation_model_id=dto.escalation_model_id,
            strategies=dto.strategies,
            temperature=dto.temperature,
            is_active=dto.is_active,
            version=dto.version,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
        )


class AgentListResponse(BaseModel):
    """Response schema for agent list."""

    agents: list[AgentResponse]
    total: int


class AgentPreviewResponse(BaseModel):
    """Response schema for agent preview (combined prompt + memory)."""

    slug: str
    name: str
    combined_prompt: str
    mandate_count: int
    guardrail_count: int
    mandate_uuids: list[str]
    guardrail_uuids: list[str]


@router.get("", response_model=AgentListResponse)
async def list_agents(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> AgentListResponse:
    """List all agents."""
    service = get_agent_service()
    agents = await service.list_agents(db, active_only=active_only, limit=limit, offset=offset)

    return AgentListResponse(
        agents=[AgentResponse.from_dto(a) for a in agents],
        total=len(agents),
    )


@router.get("/{slug}", response_model=AgentResponse)
async def get_agent(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentResponse:
    """Get a single agent by slug."""
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    return AgentResponse.from_dto(agent)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    request: AgentCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentResponse:
    """Create a new agent."""
    service = get_agent_service()

    # Check if slug already exists
    existing = await service.get_by_slug(db, request.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent '{request.slug}' already exists")

    try:
        agent = await service.create(
            db,
            slug=request.slug,
            name=request.name,
            description=request.description,
            system_prompt=request.system_prompt,
            primary_model_id=request.primary_model_id,
            fallback_models=request.fallback_models,
            escalation_model_id=request.escalation_model_id,
            strategies=request.strategies,
            temperature=request.temperature,
            is_active=request.is_active,
            changed_by=auth.key_id if auth else None,
        )
        logger.info(f"Created agent: {request.slug}")
        return AgentResponse.from_dto(agent)
    except Exception as e:
        logger.error(f"Failed to create agent: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/{slug}", response_model=AgentResponse)
async def update_agent(
    slug: str,
    request: AgentUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentResponse:
    """Update an existing agent."""
    service = get_agent_service()

    # Get agent to update
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    try:
        updated = await service.update(
            db,
            agent.id,
            name=request.name,
            description=request.description,
            system_prompt=request.system_prompt,
            primary_model_id=request.primary_model_id,
            fallback_models=request.fallback_models,
            escalation_model_id=request.escalation_model_id,
            strategies=request.strategies,
            temperature=request.temperature,
            is_active=request.is_active,
            changed_by=auth.key_id if auth else None,
            change_reason=request.change_reason,
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

        logger.info(f"Updated agent: {slug} to version {updated.version}")
        return AgentResponse.from_dto(updated)
    except Exception as e:
        logger.error(f"Failed to update agent: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{slug}", status_code=204)
async def delete_agent(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    hard_delete: bool = False,
) -> None:
    """Soft delete an agent (set is_active=False).

    Use hard_delete=true to permanently delete.
    """
    service = get_agent_service()

    # Get agent to delete
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    deleted = await service.delete(db, agent.id, hard_delete=hard_delete)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    action = "Deleted" if hard_delete else "Deactivated"
    logger.info(f"{action} agent: {slug}")


@router.get("/{slug}/preview", response_model=AgentPreviewResponse)
async def preview_agent(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentPreviewResponse:
    """Preview agent's combined system prompt with memory injection.

    Returns the agent's system prompt combined with global instructions,
    mandates, and guardrails that would be injected at runtime.
    """
    from sqlalchemy import text

    from app.services.memory.context_injector import (
        build_progressive_context,
        format_progressive_context,
    )
    from app.services.memory.service import MemoryScope

    service = get_agent_service()

    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    sections = []

    result = await db.execute(
        text("SELECT content, enabled FROM global_instructions WHERE scope = 'global'")
    )
    row = result.fetchone()
    if row and row.enabled and row.content:
        sections.append(f"<platform_context>\n{row.content}\n</platform_context>")

    sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")

    context = await build_progressive_context(
        query="",
        scope=MemoryScope.GLOBAL,
        scope_id=None,
    )

    formatted_memory = format_progressive_context(context, include_citations=True)
    if formatted_memory:
        sections.append(formatted_memory)

    combined = "\n\n".join(sections)

    mandate_uuids = [m.uuid[:8] if m.uuid else "" for m in context.mandates]
    guardrail_uuids = [g.uuid[:8] if g.uuid else "" for g in context.guardrails]

    return AgentPreviewResponse(
        slug=agent.slug,
        name=agent.name,
        combined_prompt=combined,
        mandate_count=len(context.mandates),
        guardrail_count=len(context.guardrails),
        mandate_uuids=[u for u in mandate_uuids if u],
        guardrail_uuids=[u for u in guardrail_uuids if u],
    )


class AgentMetrics(BaseModel):
    """24h metrics for an agent."""

    slug: str
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 100.0
    tokens_24h: int = 0
    cost_24h_usd: float = 0.0
    # Sparkline data (last 24 hours, 1 point per hour)
    latency_trend: list[float] = Field(default_factory=list)
    success_trend: list[float] = Field(default_factory=list)


class AgentMetricsListResponse(BaseModel):
    """Response for agent metrics list."""

    metrics: dict[str, AgentMetrics]


@router.get("/metrics/all", response_model=AgentMetricsListResponse)
async def get_all_agent_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentMetricsListResponse:
    """Get 24h metrics for all active agents.

    Note: Returns placeholder data until agent usage tracking is implemented.
    The metrics infrastructure will track agent_id in requests.
    """
    service = get_agent_service()
    agents = await service.list_agents(db, active_only=True)

    # Return placeholder metrics for each agent
    # TODO: Replace with actual metrics once agent tracking is implemented
    metrics: dict[str, AgentMetrics] = {}
    for agent in agents:
        metrics[agent.slug] = AgentMetrics(
            slug=agent.slug,
            requests_24h=0,
            avg_latency_ms=0.0,
            success_rate=100.0,
            tokens_24h=0,
            cost_24h_usd=0.0,
            latency_trend=[],
            success_trend=[],
        )

    return AgentMetricsListResponse(metrics=metrics)


@router.get("/{slug}/metrics", response_model=AgentMetrics)
async def get_agent_metrics(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentMetrics:
    """Get 24h metrics for a specific agent.

    Note: Returns placeholder data until agent usage tracking is implemented.
    """
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    # Return placeholder metrics
    # TODO: Replace with actual metrics once agent tracking is implemented
    return AgentMetrics(
        slug=agent.slug,
        requests_24h=0,
        avg_latency_ms=0.0,
        success_rate=100.0,
        tokens_24h=0,
        cost_24h_usd=0.0,
        latency_trend=[],
        success_trend=[],
    )


@router.get("/{slug}/versions")
async def get_agent_versions(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get version history for an agent."""
    service = get_agent_service()

    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    versions = await service.get_version_history(db, agent.id, limit=limit)
    return versions
