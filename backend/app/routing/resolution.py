"""Agent and model resolution.

Moved from ``app.api.complete.resolution`` per convergence-map.md C2.
Routing is now a peer of ``app.llm`` and ``app.memory``, not a sub-concern
of the HTTP completion package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from app.services.agent_model_router import (
    RoutingContext,
)
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.agent_routing import (
    inject_agent_mandates,
    resolve_agent,
)
from app.services.llm_messages import Message
from app.services.memory.context_builder_settings import (
    resolve_runtime_prompt_includes,
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

    Returns ``(resolved_model, provider, resolved_agent, mandate_injection, agent_used)``.
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
        work_context_obj = getattr(request, "work_context", None)
        work_context = work_context_obj.model_dump(exclude_none=True) if work_context_obj else None
        response_format = getattr(request, "response_format", None)
        response_type = response_format.type if response_format else None
        resolved_agent = await resolve_agent(
            request.agent_slug,
            db,
            RoutingContext(
                request_id=request_hash,
                session_id=getattr(request, "session_id", None),
                project_id=request.project_id,
                task_type=request.task_type,
                phase=getattr(request, "phase", None),
                work_context=work_context,
                has_tools=bool(getattr(request, "tools", None) or getattr(request, "execute_tools", False)),
                requires_json=response_type == "json_object",
                has_vision_input=_messages_have_vision(getattr(request, "messages", [])),
            ),
        )
        resolved_model = resolved_agent.model
        provider = resolved_agent.provider
        agent_used = resolved_agent.agent.slug
        agent_memory_config = resolved_agent.agent.memory_config
        include_mandates, include_guardrails = resolve_runtime_prompt_includes(
            agent_memory_config
        )
        agent_mandate_injection = await inject_agent_mandates(
            resolved_agent.agent,
            db,
            include_roles=request.include_roles,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            prompt_mode=request.prompt_mode or "full",
            project_id=request.project_id,
            task_type=request.task_type,
        )
        if not agent_mandate_injection.system_content.strip():
            agent_mandate_injection = None
        logger.debug(
            f"DEBUG[{request_hash}] Agent routing: {request.agent_slug} -> {resolved_model}"
        )
    else:
        from app.constants import resolve_model as resolve_model_const

        assert request.model is not None
        resolved_model = resolve_model_const(request.model)
        provider = get_provider(resolved_model)

    return resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used


def _messages_have_vision(messages: list[Any]) -> bool:
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") in {"image", "input_image"}:
                return True
            if isinstance(block, dict) and isinstance(block.get("source"), dict):
                return True
    return False


def apply_mention_override(
    request: CompletionRequest,
    resolved_model: str,
) -> tuple[str, str]:
    """Apply @mention model override if present in messages.

    Strips the @mention from the message content so the LLM doesn't see
    routing directives, and the cache key is based on clean content +
    resolved model.
    """
    # Lazy import — parse_mention is a string utility currently colocated with
    # the HTTP package; routing layer doesn't take a hard dep on api/complete.
    from app.api.complete.helpers import parse_mention, strip_mention_preserving_content_blocks

    if request.messages:
        last_user_msg = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user_msg:
            mentioned_model, _cleaned_content = parse_mention(last_user_msg.content)
            if mentioned_model:
                resolved_model = mentioned_model
                provider = get_provider(resolved_model)
                last_user_msg.content = strip_mention_preserving_content_blocks(last_user_msg.content)
                return resolved_model, provider

    provider = get_provider(resolved_model)
    return resolved_model, provider


def inject_agent_system_prompt(
    messages_dict: list[dict[str, Any]],
    agent_mandate_injection: AgentMandateInjection | None,
) -> list[dict[str, Any]]:
    """Inject agent system prompt into messages."""
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


__all__ = [
    "apply_mention_override",
    "inject_agent_system_prompt",
    "resolve_agent_and_model",
]
