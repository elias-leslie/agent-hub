"""Agent and model resolution logic for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from app.adapters.base import Message
from app.api.complete.helpers import parse_mention
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.agent_routing import (
    inject_agent_mandates,
    resolve_agent,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


async def resolve_agent_and_model(
    request: CompletionRequest,
    db: AsyncSession | None,
    request_hash: str,
) -> tuple[str, str, ResolvedAgent | None, AgentMandateInjection | None, str | None]:
    """Resolve agent and model from request.

    Args:
        request: Completion request
        db: Database session
        request_hash: Request hash for logging

    Returns:
        Tuple of (resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used)

    Raises:
        HTTPException: If agent resolution fails
    """
    from fastapi import HTTPException

    resolved_agent: ResolvedAgent | None = None
    agent_mandate_injection: AgentMandateInjection | None = None
    agent_used: str | None = None

    if request.agent_slug:
        if not db:
            raise HTTPException(
                status_code=400,
                detail="Database connection required for agent routing.",
            )
        resolved_agent = await resolve_agent(request.agent_slug, db)
        resolved_model = resolved_agent.model
        provider = resolved_agent.provider
        agent_used = resolved_agent.agent.slug
        agent_mandate_injection = await inject_agent_mandates(
            resolved_agent.agent, db, include_roles=request.include_roles
        )
        logger.debug(
            f"DEBUG[{request_hash}] Agent routing: {request.agent_slug} -> {resolved_model}"
        )
    else:
        from app.constants import resolve_model as resolve_model_const

        assert request.model is not None
        resolved_model = resolve_model_const(request.model)
        provider = get_provider(resolved_model)

    return resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used


def apply_mention_override(
    request: CompletionRequest,
    resolved_model: str,
) -> tuple[str, str]:
    """Apply @mention model override if present in messages.

    Args:
        request: Completion request
        resolved_model: Currently resolved model

    Returns:
        Tuple of (resolved_model, provider)
    """
    if request.messages:
        last_user_msg = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user_msg:
            mentioned_model, _ = parse_mention(last_user_msg.content)
            if mentioned_model:
                resolved_model = mentioned_model
                provider = get_provider(resolved_model)
                return resolved_model, provider

    # No override, return current values
    provider = get_provider(resolved_model)
    return resolved_model, provider


def inject_agent_system_prompt(
    messages_dict: list[dict[str, Any]],
    agent_mandate_injection: AgentMandateInjection | None,
) -> list[dict[str, Any]]:
    """Inject agent system prompt into messages.

    Args:
        messages_dict: Messages as dicts
        agent_mandate_injection: Agent mandate injection

    Returns:
        Messages with system prompt injected
    """
    if not agent_mandate_injection:
        return messages_dict

    from app.services.agent_routing import inject_system_prompt_into_messages

    temp_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m["role"]), content=m["content"])
        for m in messages_dict
    ]
    temp_messages = inject_system_prompt_into_messages(
        temp_messages, agent_mandate_injection.system_content
    )
    return [{"role": m.role, "content": m.content} for m in temp_messages]
