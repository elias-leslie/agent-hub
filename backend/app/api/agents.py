"""Agent management API endpoints.

CRUD operations for managing agent configurations.
"""

import logging
from datetime import datetime
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
    AgentRoutingResponse,
    AgentRoutingUpdateRequest,
    AgentUpdateRequest,
    AgentWorkloadRoutingUpdateRequest,
    ManualRoutePayload,
    ManualRouteResponse,
    WorkloadProfileSummary,
    WorkloadRoutingModeResponse,
)
from app.db import get_db
from app.models import (
    AgentRoutingProfile,
    AgentWorkloadRoutingMode,
    ManualModelRoute,
    ModelCatalogEntry,
    WorkloadProfile,
)
from app.services.adaptive_model_router import ensure_adaptive_routing_seed_data
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


def _manual_route_response(route: ManualModelRoute) -> ManualRouteResponse:
    return ManualRouteResponse(
        id=route.id,
        workload_profile=route.workload_profile,
        primary_model_id=route.primary_model_id,
        fallback_models=list(route.fallback_models or []),
        escalation_model_id=route.escalation_model_id,
        reason=route.reason,
        owner=route.owner,
        expires_at=route.expires_at.isoformat() if route.expires_at else None,
        allow_health_fallback=route.allow_health_fallback,
        enabled=route.enabled,
    )


async def _model_exists(db: AsyncSession, model_id: str | None) -> bool:
    if not model_id:
        return True
    return bool(await db.scalar(select(ModelCatalogEntry.id).where(ModelCatalogEntry.id == model_id)))


async def _validate_manual_route_payload(db: AsyncSession, payload: ManualRoutePayload) -> None:
    model_ids = [payload.primary_model_id, *payload.fallback_models]
    if payload.escalation_model_id:
        model_ids.append(payload.escalation_model_id)
    for model_id in model_ids:
        if not await _model_exists(db, model_id):
            raise HTTPException(status_code=400, detail=f"Model '{model_id}' not found in catalog")


def _parse_expires_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail="expires_at must be ISO-8601") from e


async def _upsert_manual_route(
    db: AsyncSession,
    *,
    agent_slug: str,
    workload_profile: str | None,
    payload: ManualRoutePayload,
) -> ManualModelRoute:
    await _validate_manual_route_payload(db, payload)
    route = await db.scalar(
        select(ManualModelRoute).where(
            ManualModelRoute.agent_slug == agent_slug,
            ManualModelRoute.workload_profile == workload_profile,
            ManualModelRoute.enabled == True,  # noqa: E712
        )
    )
    if route is None:
        route = ManualModelRoute(agent_slug=agent_slug, workload_profile=workload_profile)
        db.add(route)
    route.primary_model_id = payload.primary_model_id
    route.fallback_models = list(payload.fallback_models)
    route.escalation_model_id = payload.escalation_model_id
    route.reason = payload.reason
    route.owner = payload.owner
    route.expires_at = _parse_expires_at(payload.expires_at)
    route.allow_health_fallback = payload.allow_health_fallback
    route.enabled = True
    return route


async def _build_routing_response(db: AsyncSession, agent_slug: str) -> AgentRoutingResponse:
    await ensure_adaptive_routing_seed_data(db)
    profile = await db.get(AgentRoutingProfile, agent_slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Routing profile for '{agent_slug}' not found")
    overrides = (
        await db.execute(
            select(AgentWorkloadRoutingMode)
            .where(AgentWorkloadRoutingMode.agent_slug == agent_slug)
            .order_by(AgentWorkloadRoutingMode.workload_profile)
        )
    ).scalars().all()
    routes = (
        await db.execute(
            select(ManualModelRoute)
            .where(ManualModelRoute.agent_slug == agent_slug)
            .order_by(ManualModelRoute.workload_profile.nullsfirst(), ManualModelRoute.id)
        )
    ).scalars().all()
    workload_profiles = (
        await db.execute(select(WorkloadProfile).order_by(WorkloadProfile.key))
    ).scalars().all()
    return AgentRoutingResponse(
        agent_slug=profile.agent_slug,
        default_routing_mode=profile.default_routing_mode,
        risk_tier=profile.risk_tier,
        cost_policy=profile.cost_policy,
        subscription_policy=profile.subscription_policy,
        exploration_policy=profile.exploration_policy,
        quality_floor=profile.quality_floor,
        workload_profiles=[
            WorkloadProfileSummary(
                key=workload.key,
                label=workload.label,
                risk_tier=workload.risk_tier,
                default_routing_mode=workload.default_routing_mode,
            )
            for workload in workload_profiles
        ],
        workload_overrides=[
            WorkloadRoutingModeResponse(
                workload_profile=override.workload_profile,
                routing_mode=override.routing_mode,
                canary_percent=override.canary_percent,
                reason=override.reason,
                owner=override.owner,
                enabled=override.enabled,
            )
            for override in overrides
        ],
        manual_routes=[_manual_route_response(route) for route in routes],
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


@router.get("/{slug}/routing", response_model=AgentRoutingResponse)
async def get_agent_routing(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentRoutingResponse:
    """Get adaptive routing profile and manual routes for one agent."""
    await _require_agent(db, slug, active_only=False)
    return await _build_routing_response(db, slug)


@router.put("/{slug}/routing", response_model=AgentRoutingResponse)
async def update_agent_routing(
    slug: str,
    request: AgentRoutingUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentRoutingResponse:
    """Update agent-level adaptive routing policy."""
    await _require_agent(db, slug, active_only=False)
    await ensure_adaptive_routing_seed_data(db)
    profile = await db.get(AgentRoutingProfile, slug)
    if profile is None:
        profile = AgentRoutingProfile(agent_slug=slug)
        db.add(profile)
    fields_set = getattr(request, "model_fields_set", set())
    if request.default_routing_mode is not None:
        profile.default_routing_mode = request.default_routing_mode
        metadata = dict(profile.metadata_ or {})
        metadata["source"] = "user_override"
        profile.metadata_ = metadata
    if request.risk_tier is not None:
        profile.risk_tier = request.risk_tier
    if request.cost_policy is not None:
        profile.cost_policy = request.cost_policy
    if request.subscription_policy is not None:
        profile.subscription_policy = request.subscription_policy
    if request.exploration_policy is not None:
        profile.exploration_policy = request.exploration_policy
    if "quality_floor" in fields_set:
        profile.quality_floor = request.quality_floor
    if request.manual_route is not None:
        await _upsert_manual_route(db, agent_slug=slug, workload_profile=None, payload=request.manual_route)
        metadata = dict(profile.metadata_ or {})
        metadata["source"] = "manual_override"
        profile.metadata_ = metadata
    await db.commit()
    return await _build_routing_response(db, slug)


@router.put("/{slug}/routing/workloads/{workload_profile}", response_model=AgentRoutingResponse)
async def update_agent_workload_routing(
    slug: str,
    workload_profile: str,
    request: AgentWorkloadRoutingUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentRoutingResponse:
    """Update workload-specific routing policy for one agent."""
    await _require_agent(db, slug, active_only=False)
    await ensure_adaptive_routing_seed_data(db)
    if not await db.scalar(select(WorkloadProfile.key).where(WorkloadProfile.key == workload_profile)):
        raise HTTPException(status_code=404, detail=f"Workload profile '{workload_profile}' not found")
    override = await db.scalar(
        select(AgentWorkloadRoutingMode).where(
            AgentWorkloadRoutingMode.agent_slug == slug,
            AgentWorkloadRoutingMode.workload_profile == workload_profile,
        )
    )
    if override is None:
        override = AgentWorkloadRoutingMode(agent_slug=slug, workload_profile=workload_profile)
        db.add(override)
    if request.routing_mode is not None:
        override.routing_mode = request.routing_mode
    elif not override.routing_mode:
        override.routing_mode = "auto_shadow"
    if request.canary_percent is not None:
        override.canary_percent = request.canary_percent
    override.reason = request.reason
    override.owner = request.owner
    override.enabled = request.enabled
    if request.manual_route is not None:
        await _upsert_manual_route(db, agent_slug=slug, workload_profile=workload_profile, payload=request.manual_route)
    await db.commit()
    return await _build_routing_response(db, slug)


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
