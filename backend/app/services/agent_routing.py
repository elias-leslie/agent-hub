"""Agent Routing Service.

Provides unified agent routing logic for all endpoints, including:
- Agent resolution (slug -> AgentDTO)
- System prompt injection
- Fallback chain completion
- Provider adapter management

Mandates are injected via the progressive context system (semantic search)
rather than agent-specific tags.

This service consolidates routing logic previously in openai_compat.py
for use by the native /api/complete endpoint.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_service import AgentDTO, get_agent_service

# Re-exports for backward compatibility
from .agent_routing_completion import (
    complete_with_fallback,
    inject_system_prompt_into_messages,
)
from .agent_routing_models import CompletionResult, MandateInjection, ResolvedAgent
from .agent_routing_utils import (
    get_adapter,
    get_global_instructions,
    get_provider_for_model,
)

logger = logging.getLogger(__name__)

# Explicitly re-export
__all__ = [
    "ResolvedAgent",
    "MandateInjection",
    "CompletionResult",
    "get_provider_for_model",
    "get_adapter",
    "get_global_instructions",
    "resolve_agent",
    "inject_agent_mandates",
    "complete_with_fallback",
    "inject_system_prompt_into_messages",
]


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

    provider = get_provider_for_model(agent.primary_model_id)

    logger.info(f"Agent routing: {slug} -> {agent.primary_model_id} ({provider})")

    return ResolvedAgent(
        agent=agent,
        model=agent.primary_model_id,
        provider=provider,
    )


async def inject_agent_mandates(
    agent: AgentDTO,
    db: AsyncSession | None = None,
    *,
    include_roles: list[str] | None = None,
) -> MandateInjection:
    """Build system content with DB-stored prompts + agent's system prompt.

    Composition order:
    1. Global prompts from DB (is_global=true, ordered by slug)
    2. <agent_persona> - Agent-specific system prompt
    3. Role-assigned prompts from DB (agent_prompts, ordered by priority)

    Falls back to global_instructions table if no DB prompts exist.

    Args:
        agent: Agent DTO with system prompt
        db: Optional database session for fetching prompts
        include_roles: When provided, only inject prompts with matching roles.
            When None (default), injects all assigned prompts.

    Returns:
        MandateInjection with system content (no mandate UUIDs - handled by progressive context)
    """
    sections = []

    if db:
        from app.services.prompt_service import build_prompt_context

        prompt_context = await build_prompt_context(db, agent.id, include_roles=include_roles)
        if prompt_context:
            sections.append(prompt_context)
        else:
            global_instructions = await get_global_instructions(db)
            if global_instructions:
                sections.append(f"<platform_context>\n{global_instructions}\n</platform_context>")

    sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")

    return MandateInjection(
        system_content="\n\n".join(sections),
        injected_uuids=[],
    )
