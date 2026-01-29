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
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import (
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.services.agent_service import AgentDTO, get_agent_service

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


@dataclass
class ResolvedAgent:
    """Result of agent resolution."""

    agent: AgentDTO
    model: str  # Primary model ID
    provider: str  # Provider name ("claude", "gemini")


@dataclass
class MandateInjection:
    """Result of mandate injection."""

    system_content: str  # Agent system prompt + mandates
    injected_uuids: list[str]  # UUIDs of injected mandates


@dataclass
class CompletionResult:
    """Result of completion with fallback."""

    result: Any  # Adapter result
    model_used: str  # Model that produced the result
    used_fallback: bool  # Whether fallback was used


def get_provider_for_model(model: str) -> str:
    """Determine provider from model name.

    Args:
        model: Model ID (e.g., "claude-sonnet-4-5", "gemini-3-flash")

    Returns:
        Provider name ("claude" or "gemini")
    """
    if "claude" in model.lower():
        return "claude"
    elif "gemini" in model.lower():
        return "gemini"
    return "claude"  # Default


def get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get adapter instance for provider.

    Args:
        provider: Provider name ("claude" or "gemini")

    Returns:
        Adapter instance

    Raises:
        ValueError: If provider is unknown
    """
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
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
) -> MandateInjection:
    """Build system content with global instructions + agent's system prompt.

    Structure:
    1. <platform_context> - Global instructions (if enabled)
    2. <agent_persona> - Agent-specific system prompt

    Mandates are injected via the progressive context system using
    semantic search, not via agent-specific tags.

    Args:
        agent: Agent DTO with system prompt
        db: Optional database session for fetching global instructions

    Returns:
        MandateInjection with system content (no mandate UUIDs - handled by progressive context)
    """
    sections = []

    if db:
        global_instructions = await get_global_instructions(db)
        if global_instructions:
            sections.append(f"<platform_context>\n{global_instructions}\n</platform_context>")

    sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")

    return MandateInjection(
        system_content="\n\n".join(sections),
        injected_uuids=[],
    )


async def complete_with_fallback(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None = None,
) -> CompletionResult:
    """Attempt completion with agent's primary model, falling back if needed.

    Tries the primary model first, then each fallback model in order
    if the primary fails with RateLimitError or ProviderError.

    Args:
        messages: Messages to complete
        agent: Agent config with primary_model_id and fallback_models
        temperature: Temperature for sampling
        max_tokens: Optional max tokens for completion (None = model default)

    Returns:
        CompletionResult with result, model used, and fallback flag

    Raises:
        ProviderError: If all models (primary + fallbacks) fail
    """
    # Try primary model first
    primary_provider = get_provider_for_model(agent.primary_model_id)

    try:
        adapter = get_adapter(primary_provider)
        result = await adapter.complete(
            messages=messages,
            model=agent.primary_model_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return CompletionResult(
            result=result,
            model_used=agent.primary_model_id,
            used_fallback=False,
        )
    except (RateLimitError, ProviderError) as e:
        logger.warning(f"Primary model {agent.primary_model_id} failed for agent {agent.slug}: {e}")

    # Try fallback models
    for fallback_model in agent.fallback_models or []:
        fallback_provider = get_provider_for_model(fallback_model)
        try:
            adapter = get_adapter(fallback_provider)
            result = await adapter.complete(
                messages=messages,
                model=fallback_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            logger.info(f"Agent {agent.slug} used fallback model: {fallback_model}")
            return CompletionResult(
                result=result,
                model_used=fallback_model,
                used_fallback=True,
            )
        except (RateLimitError, ProviderError) as e:
            logger.warning(f"Fallback model {fallback_model} also failed: {e}")
            continue

    # All models failed
    raise ProviderError(
        provider=primary_provider,
        message=f"All models failed for agent {agent.slug}: primary={agent.primary_model_id}, "
        f"fallbacks={agent.fallback_models}",
    )


def inject_system_prompt_into_messages(
    messages: list[Message],
    system_content: str,
) -> list[Message]:
    """Inject system content into messages list.

    If a system message already exists, prepends the new content.
    Otherwise, inserts a new system message at the beginning.

    Args:
        messages: Original message list (will not be modified)
        system_content: System content to inject

    Returns:
        New message list with injected system content
    """
    messages = messages.copy()

    system_idx = next(
        (i for i, m in enumerate(messages) if m.role == "system"),
        None,
    )

    if system_idx is not None:
        # Prepend to existing system message
        messages[system_idx] = Message(
            role="system",
            content=f"{system_content}\n\n---\n\n{messages[system_idx].content}",
        )
    else:
        # Insert new system message at beginning
        messages.insert(0, Message(role="system", content=system_content))

    return messages
