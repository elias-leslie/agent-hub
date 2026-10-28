"""Utility functions for Agent Routing Service."""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.routing.registry import get_provider_for_model
from app.services.agent_dto import AgentDTO
from app.services.agent_model_router import RoutingContext, resolve_model_route
from app.services.agent_service import get_agent_service

from .agent_routing_models import MandateInjection, ResolvedAgent

logger = logging.getLogger(__name__)


async def resolve_agent(
    slug: str,
    db: AsyncSession,
    routing_context: RoutingContext | None = None,
) -> ResolvedAgent:
    """Resolve agent slug to agent config, model, and provider. Raises 404 if not found."""
    if slug == "memory-curator":
        from app.services.curator_retirement import curator_unavailable

        curator_unavailable()
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"error": {"message": f"Agent '{slug}' not found", "type": "invalid_request_error", "code": "agent_not_found"}},
        )
    routed_agent, _route = await resolve_model_route(db, agent, routing_context)
    model = routed_agent.primary_model_id
    provider = get_provider_for_model(model)
    logger.info(
        "Agent routing: %s -> %s (%s)",
        slug,
        model,
        provider,
    )
    return ResolvedAgent(
        agent=routed_agent,
        model=model,
        provider=provider,
    )


async def inject_agent_mandates(
    agent: AgentDTO,
    db: AsyncSession | None = None,
    *,
    include_roles: list[str] | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    prompt_mode: str = "full",
    project_id: str | None = None,
    task_type: str | None = None,
) -> MandateInjection:
    """Build only agent-specific prompt/permission content.

    Shared operator prompts and memory are injected once through the canonical
    context delivery path later in request setup.
    """
    if prompt_mode == "none":
        return MandateInjection(system_content="", injected_uuids=[])

    sections: list[str] = []
    if db:
        from app.services.runtime_prompt_stack import (
            collect_runtime_prompt_sections,
            join_runtime_prompt_sections,
        )

        runtime_sections = await collect_runtime_prompt_sections(
            db,
            agent,
            include_roles=include_roles,
            task_type=task_type,
            project_id=project_id,
            include_global_prompts=False,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
        )
        system_content = join_runtime_prompt_sections(runtime_sections)
        return MandateInjection(system_content=system_content, injected_uuids=[])

    if agent.system_prompt:
        sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")
    return MandateInjection(system_content="\n\n".join(sections), injected_uuids=[])
