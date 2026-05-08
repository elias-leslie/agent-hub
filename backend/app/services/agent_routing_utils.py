"""Utility functions for Agent Routing Service."""

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.adapters.registry import get_adapter as registry_get_adapter
from app.adapters.registry import get_provider_for_model
from app.services.adaptive_model_router import RoutingContext, resolve_model_route
from app.services.agent_dto import AgentDTO
from app.services.agent_service import get_agent_service

from .agent_routing_models import MandateInjection, ResolvedAgent

logger = logging.getLogger(__name__)


def get_adapter(provider: str) -> ProviderAdapter:
    """Get adapter instance for provider (fresh/uncached each call)."""
    return registry_get_adapter(provider)


async def resolve_agent(
    slug: str,
    db: AsyncSession,
    routing_context: RoutingContext | None = None,
) -> ResolvedAgent:
    """Resolve agent slug to agent config, model, and provider. Raises 404 if not found."""
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"error": {"message": f"Agent '{slug}' not found", "type": "invalid_request_error", "code": "agent_not_found"}},
        )
    routed_agent, route = await resolve_model_route(db, agent, routing_context)
    model = routed_agent.primary_model_id
    provider = get_provider_for_model(model)
    logger.info(
        "Agent routing: %s -> %s (%s) mode=%s workload=%s decision=%s",
        slug,
        model,
        provider,
        route.mode,
        route.workload_profile,
        route.decision_id,
    )
    return ResolvedAgent(
        agent=routed_agent,
        model=model,
        provider=provider,
        routing_mode=route.mode,
        workload_profile=route.workload_profile,
        routing_decision_id=route.decision_id,
        auto_candidate_model_id=route.auto_candidate_model_id,
        routing_canary_percent=route.canary_percent,
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
    """Build system content with DB-stored prompts + agent's system prompt."""
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
            prompt_mode=prompt_mode,
            include_global_prompts=True,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            include_persona_context=(prompt_mode == "full"),
        )
        system_content = join_runtime_prompt_sections(runtime_sections)
        return MandateInjection(system_content=system_content, injected_uuids=[])

    if agent.system_prompt:
        sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")
    if project_id:
        perm_block = await _build_project_permissions_block(
            project_id, None, agent_slug=agent.slug,
        )
        if perm_block:
            sections.append(perm_block)
    return MandateInjection(system_content="\n\n".join(sections), injected_uuids=[])


_TIER_DESCRIPTIONS: dict[str, str] = {
    "off": "You have NO access to this project. Do not attempt any tool calls.",
    "read": "You have READ-ONLY access. You may use read_file only. Do NOT write files or execute commands.",
    "full": "You have FULL trusted-project access including bash execution.",
}
_TIER_LABELS: dict[str, str] = {
    "off": "off (all access blocked)",
    "read": "read (read-only, writes blocked)",
    "full": "full (trusted project access)",
}


@dataclass(frozen=True)
class _PermissionSnapshot:
    project_id: str
    permission_tier: str


async def _fetch_permissions(project_id: str, db: AsyncSession | None):
    from app.services.project_permission_service import (
        get_project_permission,
        list_project_permissions,
    )
    if db:
        return await get_project_permission(db, project_id), await list_project_permissions(db)
    from app.db import async_session
    async with async_session() as fresh_db:
        perm = await get_project_permission(fresh_db, project_id)
        all_perms = await list_project_permissions(fresh_db)
        current = (
            _PermissionSnapshot(perm.project_id, perm.permission_tier)
            if perm is not None
            else None
        )
        return current, [
            _PermissionSnapshot(p.project_id, p.permission_tier)
            for p in all_perms
        ]


def _build_cross_project_lines(all_perms, project_id: str) -> list[str]:
    from app.models.project_permission import normalize_permission_tier

    other_perms = [p for p in all_perms if p.project_id != project_id]
    if not other_perms:
        return []
    lines = ["", "Cross-project permissions (enforced on read_file/write_file, best-effort on bash):"]
    for p in other_perms:
        tier = normalize_permission_tier(p.permission_tier) or p.permission_tier
        lines.append(f"- {p.project_id}: {_TIER_LABELS.get(tier, tier)}")
    lines += ["", "Note: Use read_file/write_file for cross-project file access — these are permission-enforced. bash commands referencing restricted project paths will also be blocked."]
    return lines


async def _build_project_permissions_block(
    project_id: str,
    db: AsyncSession | None,
    *,
    agent_slug: str | None = None,
) -> str | None:
    try:
        from app.models.project_permission import normalize_permission_tier
        from app.services.project_permission_service import get_visible_tools_for_project

        perm, all_perms = await _fetch_permissions(project_id, db)
        if perm is None:
            return None
        tier = normalize_permission_tier(perm.permission_tier) or perm.permission_tier
        if agent_slug == "persona":
            from app.services.tools.persona_tool_surface import (
                format_persona_operator_tools_for_tier,
            )

            tools_list = format_persona_operator_tools_for_tier(tier)
        else:
            visible_tool_names = await get_visible_tools_for_project(project_id, db)
            tools_list = ", ".join(sorted(visible_tool_names)) or "none"
        lines = [
            "<project_permissions>",
            f"Current project: {project_id}",
            f"Permission tier: {tier}",
            f"Allowed tools: {tools_list}",
            _TIER_DESCRIPTIONS.get(tier, "Unknown permission tier."),
            *_build_cross_project_lines(all_perms, project_id),
            "</project_permissions>",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to build project permissions block: %s", e)
        return None
