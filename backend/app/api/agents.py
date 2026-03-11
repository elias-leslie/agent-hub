"""Agent management API endpoints.

CRUD operations for managing agent configurations.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers.agent_benchmarks import get_agent_benchmark_dashboard
from app.api.helpers.agent_metrics import compute_agent_metrics
from app.api.helpers.agent_preview import build_agent_preview
from app.api.schemas.agent_schemas import (
    AgentBenchmarkDashboard,
    AgentCreateRequest,
    AgentListResponse,
    AgentMetrics,
    AgentMetricsListResponse,
    AgentPreviewResponse,
    AgentResponse,
    AgentUpdateRequest,
)
from app.db import get_db
from app.services.agent_service import get_agent_service
from app.services.api_key_auth import AuthenticatedKey, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    active_only: bool = True,
    is_coding_agent: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AgentListResponse:
    """List all agents.

    Args:
        active_only: Only return active agents (default True)
        is_coding_agent: Filter by coding agent flag. If True, only coding agents.
            If False, only non-coding. If None (default), no filter.
    """
    service = get_agent_service()
    agents = await service.list_agents(
        db, active_only=active_only, coding_only=is_coding_agent, limit=limit, offset=offset
    )

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
            thinking_level=request.thinking_level,
            verbosity_level=request.verbosity_level,
            is_active=request.is_active,
            is_coding_agent=request.is_coding_agent,
            tool_permissions=request.tool_permissions.model_dump()
            if request.tool_permissions
            else None,
            memory_config=request.memory_config,
            max_concurrency=request.max_concurrency,
            max_subagent_concurrency=request.max_subagent_concurrency,
            daily_token_budget=request.daily_token_budget,
            hourly_request_limit=request.hourly_request_limit,
            timeout_seconds=request.timeout_seconds,
            changed_by=str(auth.key_id) if auth else None,
        )
        logger.info(f"Created agent: {request.slug}")
        return AgentResponse.from_dto(agent)
    except HTTPException:
        raise
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

    if request.tool_permissions is not None:
        logger.debug(f"Received tool_permissions: {request.tool_permissions.model_dump()}")
    else:
        logger.debug("No tool_permissions in request")

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
            thinking_level=request.thinking_level,
            verbosity_level=request.verbosity_level,
            is_active=request.is_active,
            is_coding_agent=request.is_coding_agent,
            tool_permissions=request.tool_permissions.model_dump()
            if request.tool_permissions
            else None,
            memory_config=request.memory_config,
            max_concurrency=request.max_concurrency,
            max_subagent_concurrency=request.max_subagent_concurrency,
            daily_token_budget=request.daily_token_budget,
            hourly_request_limit=request.hourly_request_limit,
            timeout_seconds=request.timeout_seconds,
            changed_by=str(auth.key_id) if auth else None,
            change_reason=request.change_reason,
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

        logger.info(f"Updated agent: {slug} to version {updated.version}")
        return AgentResponse.from_dto(updated)
    except HTTPException:
        raise
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
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    (
        combined,
        mandate_count,
        guardrail_count,
        mandate_uuids,
        guardrail_uuids,
    ) = await build_agent_preview(db, agent)

    return AgentPreviewResponse(
        slug=agent.slug,
        name=agent.name,
        combined_prompt=combined,
        mandate_count=mandate_count,
        guardrail_count=guardrail_count,
        mandate_uuids=mandate_uuids,
        guardrail_uuids=guardrail_uuids,
    )


@router.get("/metrics/all", response_model=AgentMetricsListResponse)
async def get_all_agent_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentMetricsListResponse:
    """Get 24h metrics for all active agents.

    Queries request_logs table using agent_slug column for real metrics.
    """
    service = get_agent_service()
    agents = await service.list_agents(db, active_only=True)

    metrics: dict[str, AgentMetrics] = {}
    for agent in agents:
        metrics[agent.slug] = await compute_agent_metrics(db, agent.slug)

    return AgentMetricsListResponse(metrics=metrics)


@router.get("/{slug}/metrics", response_model=AgentMetrics)
async def get_agent_metrics(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentMetrics:
    """Get 24h metrics for a specific agent.

    Queries request_logs table using agent_slug column for real metrics.
    """
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    return await compute_agent_metrics(db, agent.slug)


@router.get("/{slug}/benchmarks", response_model=AgentBenchmarkDashboard)
async def get_agent_benchmarks(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    days: int = 30,
    limit: int = 20,
    suite_id: str | None = None,
) -> AgentBenchmarkDashboard:
    """Get persisted benchmark history and regression dashboard for one agent."""
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    return await get_agent_benchmark_dashboard(db, agent.slug, days=days, limit=limit, suite_id=suite_id)


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
