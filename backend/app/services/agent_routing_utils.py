"""Utility functions for Agent Routing Service."""

import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.adapters.registry import (
    get_adapter as registry_get_adapter,
)
from app.adapters.registry import (
    get_provider_for_model,
)
from app.services.agent_dto import AgentDTO
from app.services.agent_service import get_agent_service

from .agent_routing_models import MandateInjection, ResolvedAgent

logger = logging.getLogger(__name__)


async def get_global_instructions(db: AsyncSession) -> str | None:
    """Fetch global instructions from database.

    Returns:
        Global instructions content if enabled, None otherwise.
    """
    try:
        result = await db.execute(
            text("SELECT content, enabled FROM global_instructions WHERE scope = 'global'")
        )
        row = result.fetchone()
        if row and row.enabled and row.content:
            logger.info(
                f"Global instructions fetched: enabled={row.enabled}, length={len(row.content)}"
            )
            content: str = row.content
            return content
        else:
            logger.info(f"Global instructions not available: row={row is not None}")
    except Exception as e:
        logger.warning(f"Failed to fetch global instructions: {e}")
    return None


def get_adapter(provider: str) -> ProviderAdapter:
    """Get adapter instance for provider.

    Note: This creates a fresh (uncached) instance each call, matching the
    original behavior of this module. For cached instances, use the registry
    directly via ``app.adapters.registry.get_adapter()``.

    Args:
        provider: Provider name

    Returns:
        Adapter instance

    Raises:
        ValueError: If provider is unknown
    """
    return registry_get_adapter(provider)


async def resolve_agent(
    slug: str,
    db: AsyncSession,
) -> ResolvedAgent:
    """Resolve agent slug to agent config, model, and provider.

    Args:
        slug: Agent slug (e.g., "coder", "planner")
        db: Database session

    Returns:
        ResolvedAgent with agent config, model, and provider

    Raises:
        HTTPException: If agent not found (404)
    """
    service = get_agent_service()
    agent = await service.get_by_slug(db, slug)

    if not agent:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Agent '{slug}' not found",
                    "type": "invalid_request_error",
                    "code": "agent_not_found",
                }
            },
        )

    model = agent.primary_model_id
    provider = get_provider_for_model(model)

    logger.info(f"Agent routing: {slug} -> {model} ({provider})")

    return ResolvedAgent(
        agent=agent,
        model=model,
        provider=provider,
    )


async def inject_agent_mandates(
    agent: AgentDTO,
    db: AsyncSession | None = None,
    *,
    include_roles: list[str] | None = None,
    prompt_mode: str = "full",
    project_id: str | None = None,
) -> MandateInjection:
    """Build system content with DB-stored prompts + agent's system prompt.

    Composition order (varies by prompt_mode):
    1. Global prompts from DB (is_global=true, ordered by slug)  [full, minimal]
    2. <agent_persona> - Agent-specific system prompt             [all modes]
    3. <persona_context> - Personality, journal, user context     [full only]
    4. Role-assigned prompts from DB (agent_prompts, priority)    [full, minimal]
    5. <project_permissions> - Permission tier enforcement hints  [when project_id set]

    Prompt modes:
    - "full": Everything — persona context, personality, journal, user_context,
              heartbeat_instructions, role prompts
    - "minimal": System prompt + role prompts only (for heartbeat/sub-agent calls)
    - "none": Base system prompt only (no prompts, no persona context)

    Falls back to global_instructions table if no DB prompts exist.

    Args:
        agent: Agent DTO with system prompt
        db: Optional database session for fetching prompts
        include_roles: When provided, only inject prompts with matching roles.
            When None (default), injects all assigned prompts.
        prompt_mode: Context injection mode — "full", "minimal", or "none"
        project_id: When set, injects a <project_permissions> block describing
            the agent's allowed tools for this project.

    Returns:
        MandateInjection with system content
    """
    sections = []

    # Global + role prompts (full and minimal modes)
    if db and prompt_mode != "none":
        from app.services.prompt_service import build_prompt_context

        prompt_context = await build_prompt_context(db, agent.id, include_roles=include_roles)
        if prompt_context:
            sections.append(prompt_context)
        else:
            global_instructions = await get_global_instructions(db)
            if global_instructions:
                sections.append(f"<platform_context>\n{global_instructions}\n</platform_context>")

    # Agent persona block (always included)
    sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")

    # Full persona context (full mode only)
    if db and prompt_mode == "full":
        from app.services.persona_service import get_persona_context_for_agent

        persona_context = await get_persona_context_for_agent(db, agent.id)
        if persona_context:
            sections.append(f"<persona_context>\n{persona_context}\n</persona_context>")

    # Project permission soft enforcement
    if project_id:
        perm_block = await _build_project_permissions_block(project_id, db)
        if perm_block:
            sections.append(perm_block)

    return MandateInjection(
        system_content="\n\n".join(sections),
        injected_uuids=[],
    )


# Tier descriptions for prompt injection
_TIER_DESCRIPTIONS: dict[str, str] = {
    "off": "You have NO access to this project. Do not attempt any tool calls.",
    "read": (
        "You have READ-ONLY access. You may use read_file, consult_agent, "
        "and other read tools. Do NOT write files or execute commands."
    ),
    "write": (
        "You have READ+WRITE access. You may read and write files. "
        "Do NOT use bash or execute commands."
    ),
    "yolo": "You have FULL access including bash execution.",
}


async def _build_project_permissions_block(
    project_id: str, db: AsyncSession | None
) -> str | None:
    """Build a <project_permissions> XML block for prompt injection.

    Includes the current project's full permission details plus a
    cross-project permission summary for all other registered projects.
    """
    try:
        from app.services.project_permission_service import (
            get_project_permission,
            get_tools_for_tier,
            list_project_permissions,
        )

        if db:
            perm = await get_project_permission(db, project_id)
            all_perms = await list_project_permissions(db)
        else:
            from app.db import async_session

            async with async_session() as fresh_db:
                perm = await get_project_permission(fresh_db, project_id)
                all_perms = await list_project_permissions(fresh_db)

        if perm is None:
            return None

        tier = perm.permission_tier
        description = _TIER_DESCRIPTIONS.get(tier, "Unknown permission tier.")
        allowed_tools = get_tools_for_tier(tier)
        tools_list = ", ".join(sorted(allowed_tools)) if allowed_tools else "none"

        lines = [
            "<project_permissions>",
            f"Current project: {project_id}",
            f"Permission tier: {tier}",
            f"Allowed tools: {tools_list}",
            description,
        ]

        # Cross-project permission map
        other_perms = [p for p in all_perms if p.project_id != project_id]
        if other_perms:
            tier_labels = {
                "off": "off (all access blocked)",
                "read": "read (read-only, writes blocked)",
                "write": "write (read + write files, no bash)",
                "yolo": "yolo (full access)",
            }
            lines.append("")
            lines.append("Cross-project permissions (enforced on read_file/write_file, best-effort on bash):")
            for p in other_perms:
                label = tier_labels.get(p.permission_tier, p.permission_tier)
                lines.append(f"- {p.project_id}: {label}")
            lines.append("")
            lines.append(
                "Note: Use read_file/write_file for cross-project file access — "
                "these are permission-enforced. bash commands referencing restricted "
                "project paths will also be blocked."
            )

        lines.append("</project_permissions>")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to build project permissions block: %s", e)
        return None
