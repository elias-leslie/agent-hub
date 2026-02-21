"""Completion logic for Agent Routing Service."""

import logging
from typing import Any

from app.adapters.base import (
    Message,
    ProviderError,
    RateLimitError,
)
from app.services.agent_dto import AgentDTO

from .agent_routing_models import CompletionResult
from .agent_routing_utils import get_adapter, get_provider_for_model

logger = logging.getLogger(__name__)


async def complete_with_fallback(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None = None,
    tools: list[Any] | None = None,
    thinking_level: str | None = None,
) -> CompletionResult:
    """Attempt completion with agent's primary model, falling back if needed.

    Tries the primary model first, then each fallback model in order
    if the primary fails with RateLimitError or ProviderError.

    Args:
        messages: Messages to complete
        agent: Agent config with primary_model_id and fallback_models
        temperature: Temperature for sampling
        max_tokens: Optional max tokens for completion (None = model default)
        tools: Optional tool definitions to pass to the model
        thinking_level: Optional thinking level for models that support it

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
            tools=tools,
            thinking_level=thinking_level,
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
                tools=tools,
                thinking_level=thinking_level,
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
