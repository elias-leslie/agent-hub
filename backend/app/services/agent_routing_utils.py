"""Utility functions for Agent Routing Service."""

import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.openrouter import OpenRouterAdapter
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


def get_provider_for_model(model: str) -> str:
    """Determine provider from model name.

    Args:
        model: Model ID (e.g., "claude-sonnet-4-5", "gemini-3-flash")

    Returns:
        Provider name ("claude", "gemini", "openrouter", or "openai")
    """
    model_lower = model.lower()
    if model_lower.startswith("openrouter/") or model_lower.startswith("or/"):
        return "openrouter"
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    elif "gpt" in model_lower or "openai" in model_lower:
        return "openai"
    return "claude"  # Default


def get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter | OpenRouterAdapter:
    """Get adapter instance for provider.

    Args:
        provider: Provider name ("claude", "gemini", or "openrouter")

    Returns:
        Adapter instance

    Raises:
        ValueError: If provider is unknown
    """
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    elif provider == "openrouter":
        return OpenRouterAdapter()
    raise ValueError(f"Unknown provider: {provider}")


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
        MandateInjection with system content
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
