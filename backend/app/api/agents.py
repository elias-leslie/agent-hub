"""Agent management API endpoints.

CRUD operations for managing agent configurations.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers.agent_benchmarks import get_agent_benchmark_dashboard, get_agent_benchmark_run
from app.api.helpers.agent_metrics import compute_agent_metrics
from app.api.helpers.agent_preview import build_agent_preview
from app.api.schemas.agent_schemas import (
    AgentBenchmarkDashboard,
    AgentBenchmarkRunDetail,
    AgentCreateRequest,
    AgentListResponse,
    AgentMetrics,
    AgentMetricsListResponse,
    AgentPreviewResponse,
    AgentResponse,
    AgentUpdateRequest,
)
from app.db import get_db
from app.models import RequestLog, Session
from app.services.agent_service import AgentDTO, get_agent_service
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.memory.context_builder_settings import resolve_effective_memory_config
from app.services.memory.settings import get_memory_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _build_agent_response(
    db: AsyncSession,
    agent: AgentDTO,
) -> AgentResponse:
    settings = await get_memory_settings(db)
    return AgentResponse.from_dto(
        agent,
        effective_memory_config=resolve_effective_memory_config(
            settings,
            agent.memory_config,
        ),
    )


async def _require_agent(db: AsyncSession, slug: str, *, active_only: bool = True) -> AgentDTO:
    """Fetch agent by slug or raise 404."""
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug, active_only=active_only)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
    return agent


def _agent_create_kwargs(request: AgentCreateRequest, auth: AuthenticatedKey | None) -> dict[str, Any]:
    """Map an AgentCreateRequest to keyword arguments for AgentService.create."""
    return dict(
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
        memory_config=request.memory_config.model_dump(exclude_none=True) if request.memory_config else None,
        max_concurrency=request.max_concurrency,
        max_subagent_concurrency=request.max_subagent_concurrency,
        daily_token_budget=request.daily_token_budget,
        hourly_request_limit=request.hourly_request_limit,
        timeout_seconds=request.timeout_seconds,
        changed_by=str(auth.key_id) if auth else None,
    )


def _agent_update_kwargs(request: AgentUpdateRequest, auth: AuthenticatedKey | None) -> dict[str, Any]:
    """Map an AgentUpdateRequest to keyword arguments for AgentService.update."""
    return dict(
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
        memory_config=request.memory_config.model_dump(exclude_none=True) if request.memory_config else None,
        max_concurrency=request.max_concurrency,
        max_subagent_concurrency=request.max_subagent_concurrency,
        daily_token_budget=request.daily_token_budget,
        hourly_request_limit=request.hourly_request_limit,
        timeout_seconds=request.timeout_seconds,
        changed_by=str(auth.key_id) if auth else None,
        change_reason=request.change_reason,
    )


def _build_preview_response(agent: AgentDTO, preview: dict[str, Any]) -> AgentPreviewResponse:
    """Construct AgentPreviewResponse from raw preview dict."""
    return AgentPreviewResponse(
        slug=agent.slug,
        name=agent.name,
        **{k: preview[k] for k in (
            "combined_prompt",
            "full_context",
            "memory_query",
            "memory_debug",
            "loaded_memory_uuids",
            "reference_uuids",
            "reference_index_uuids",
            "mandate_count",
            "guardrail_count",
            "mandate_uuids",
            "guardrail_uuids",
            "task_type",
            "phase",
            "project_id",
            "task_prompt",
            "sections",
            "prompt_budget",
            "full_context_estimated_tokens",
        )},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


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

    settings = await get_memory_settings(db)
    return AgentListResponse(
        agents=[
            AgentResponse.from_dto(
                agent,
                effective_memory_config=resolve_effective_memory_config(
                    settings,
                    agent.memory_config,
                ),
            )
            for agent in agents
        ],
        total=len(agents),
    )


@router.get("/{slug}", response_model=AgentResponse)
async def get_agent(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentResponse:
    """Get a single agent by slug."""
    agent = await _require_agent(db, slug, active_only=False)
    return await _build_agent_response(db, agent)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    request: AgentCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentResponse:
    """Create a new agent."""
    service = get_agent_service()

    existing = await service.get_by_slug(db, request.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent '{request.slug}' already exists")

    try:
        agent = await service.create(db, **_agent_create_kwargs(request, auth))
        logger.info(f"Created agent: {request.slug}")
        return await _build_agent_response(db, agent)
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

    agent = await _require_agent(db, slug, active_only=False)

    try:
        updated = await service.update(db, agent.id, **_agent_update_kwargs(request, auth))
        if not updated:
            raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

        logger.info(f"Updated agent: {slug} to version {updated.version}")
        return await _build_agent_response(db, updated)
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
    agent = await _require_agent(db, slug, active_only=False)

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
    task_type: Annotated[str | None, Query(description="Preview mode: chat, heartbeat, wake, or review")] = None,
    project_id: Annotated[str | None, Query(description="Optional project scope for permission and memory preview")] = None,
    phase: Annotated[str | None, Query(description="Optional phase/event hint for memory and task prompt preview")] = None,
    prompt_input: Annotated[str | None, Query(description="Optional task input placeholder for wake/review preview")] = None,
) -> AgentPreviewResponse:
    """Preview agent's combined system prompt with memory injection.

    Returns the agent's system prompt combined with global instructions,
    mandates, and guardrails that would be injected at runtime.
    """
    agent = await _require_agent(db, slug)
    preview = await build_agent_preview(
        db,
        agent,
        task_type=task_type,
        project_id=project_id,
        phase=phase,
        prompt_input=prompt_input,
    )
    return _build_preview_response(agent, preview)


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
    agent = await _require_agent(db, slug)
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
    agent = await _require_agent(db, slug)
    return await get_agent_benchmark_dashboard(db, agent.slug, days=days, limit=limit, suite_id=suite_id)


@router.get("/{slug}/benchmarks/{run_id}", response_model=AgentBenchmarkRunDetail)
async def get_agent_benchmark_run_detail(
    slug: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentBenchmarkRunDetail:
    """Get one benchmark run with individual attempt results for drill-down."""
    agent = await _require_agent(db, slug)
    result = await get_agent_benchmark_run(db, agent.slug, run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found")
    return result


@router.get("/{slug}/versions")
async def get_agent_versions(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get version history for an agent."""
    service = get_agent_service()
    agent = await _require_agent(db, slug)
    return await service.get_version_history(db, agent.id, limit=limit)


@router.get("/{slug}/activity")
async def get_agent_activity(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Return compact recent sessions and request logs for one agent."""
    agent = await _require_agent(db, slug)
    session_filters = [Session.agent_slug == agent.slug]
    if external_id:
        session_filters.append(Session.external_id == external_id)
    session_rows = (
        await db.execute(
            select(Session)
            .where(*session_filters)
            .order_by(Session.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    session_ids = [row.id for row in session_rows]

    request_filters = [RequestLog.agent_slug == agent.slug]
    if external_id:
        request_filters = [RequestLog.session_id.in_(session_ids)] if session_ids else [RequestLog.id == -1]
    request_rows = (
        await db.execute(
            select(RequestLog)
            .where(*request_filters)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "agent_slug": agent.slug,
        "sessions": [
            {
                "id": row.id,
                "project_id": row.project_id,
                "external_id": row.external_id,
                "model": row.model,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "models_used": row.models_used or [],
                "providers_used": row.providers_used or [],
                "health_detail": row.health_detail,
                "summary_outcome": row.summary_outcome,
                "current_branch": row.current_branch,
            }
            for row in session_rows
        ],
        "requests": [
            {
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "model": row.model,
                "status_code": row.status_code,
                "latency_ms": row.latency_ms,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "timed_out": row.timed_out,
                "used_fallback": row.used_fallback,
                "fallback_model": row.fallback_model,
                "session_id": row.session_id,
            }
            for row in request_rows
        ],
    }
