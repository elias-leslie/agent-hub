"""Completion logic for Agent Routing Service."""

import logging

from app.adapters.base import (
    Message,
    ProviderError,
    RateLimitError,
)
from app.services.agent_dto import AgentDTO

from .agent_routing_models import CompletionResult
from .agent_routing_utils import get_adapter, get_provider_for_model

logger = logging.getLogger(__name__)

_COMPLETION_ERRORS = (RateLimitError, ProviderError, RuntimeError)


async def _try_model(
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
) -> object | None:
    """Attempt completion with a single model; return result or None on failure."""
    provider = get_provider_for_model(model)
    try:
        adapter = get_adapter(provider)
        return await adapter.complete(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            thinking_level=thinking_level,
        )
    except _COMPLETION_ERRORS as e:
        logger.warning("Model %s failed: %s", model, e)
        return None


async def _try_primary(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
) -> CompletionResult | None:
    """Try the primary model; return CompletionResult or None on failure."""
    result = await _try_model(messages, agent.primary_model_id, temperature, max_tokens, tools, thinking_level)
    if result is None:
        logger.warning("Primary model %s failed for agent %s", agent.primary_model_id, agent.slug)
        return None
    return CompletionResult(result=result, model_used=agent.primary_model_id, used_fallback=False)


async def _try_fallbacks(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
) -> CompletionResult | None:
    """Try each fallback model in order; return first success or None."""
    for fallback_model in agent.fallback_models or []:
        result = await _try_model(messages, fallback_model, temperature, max_tokens, tools, thinking_level)
        if result is not None:
            logger.info("Agent %s used fallback model: %s", agent.slug, fallback_model)
            return CompletionResult(result=result, model_used=fallback_model, used_fallback=True)
    return None


async def _try_escalation(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    tried_models: set[str],
) -> CompletionResult | None:
    """Try the escalation model if configured and not already tried."""
    escalation = agent.escalation_model_id
    if not escalation or escalation in tried_models:
        return None
    result = await _try_model(messages, escalation, temperature, max_tokens, tools, thinking_level)
    if result is None:
        return None
    logger.info("Agent %s escalated to model: %s", agent.slug, escalation)
    return CompletionResult(result=result, model_used=escalation, used_fallback=True)


async def complete_with_fallback(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None = None,
    tools: list[dict[str, object]] | None = None,
    thinking_level: str | None = None,
) -> CompletionResult:
    """Attempt completion using primary → fallbacks → escalation model chain.

    Raises:
        ProviderError: If all models (primary + fallbacks + escalation) fail
    """
    args = (messages, agent, temperature, max_tokens, tools, thinking_level)

    primary_result = await _try_primary(*args)
    if primary_result is not None:
        return primary_result

    fallback_result = await _try_fallbacks(*args)
    if fallback_result is not None:
        return fallback_result

    tried_models = {agent.primary_model_id} | set(agent.fallback_models or [])
    escalation_result = await _try_escalation(*args, tried_models=tried_models)
    if escalation_result is not None:
        return escalation_result

    primary_provider = get_provider_for_model(agent.primary_model_id)
    raise ProviderError(
        provider=primary_provider,
        message=f"All models failed for agent {agent.slug}: primary={agent.primary_model_id}, "
        f"fallbacks={agent.fallback_models}, escalation={agent.escalation_model_id}",
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
        messages[system_idx] = Message(
            role="system",
            content=f"{system_content}\n\n---\n\n{messages[system_idx].content}",
        )
    else:
        messages.insert(0, Message(role="system", content=system_content))

    return messages
