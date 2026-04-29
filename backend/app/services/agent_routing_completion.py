"""Completion logic for Agent Routing Service."""

import asyncio
import logging
import math
import time
from typing import NoReturn

from app.adapters.base import (
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.registry import list_providers
from app.adapters.thinking import get_thinking_config
from app.constants.catalog import get_model_capabilities
from app.services.agent_dto import AgentDTO
from app.services.circuit_breaker import CircuitBreakerManager
from app.services.health_prober import record_provider_failure, record_provider_success

from .agent_routing_models import CompletionResult
from .agent_routing_utils import get_adapter, get_provider_for_model

logger = logging.getLogger(__name__)

_COMPLETION_ERRORS = (RateLimitError, ProviderError, RuntimeError, asyncio.TimeoutError)
_DEFAULT_RATE_LIMIT_COOLDOWN = 60.0
_UNSUPPORTED_NATIVE_THINKING_PROVIDERS = {"codex", "openai", "openrouter", "zhipu", "minimax", "xai"}
_RATE_LIMIT_BREAKER = CircuitBreakerManager(list_providers())


def _format_fallback_reason(error: BaseException | None) -> str | None:
    """Return a compact, user-visible explanation for a fallback trigger."""
    if error is None:
        return None
    return f"{type(error).__name__}: {error}"


def _resolve_retry_after_seconds(error: RateLimitError) -> float:
    """Return the cooldown window to enforce for a provider rate limit."""
    retry_after = error.retry_after
    if retry_after is None or retry_after <= 0:
        return _DEFAULT_RATE_LIMIT_COOLDOWN
    return float(retry_after)


async def get_provider_rate_limit_cooldown_remaining(provider: str) -> float | None:
    """Return remaining seconds for an active provider rate-limit cooldown."""
    return await _RATE_LIMIT_BREAKER.get_cooldown_remaining(provider)


async def _active_cooldown_error(provider: str) -> RateLimitError | None:
    """Return a synthetic RateLimitError when a provider cooldown is still active."""
    remaining = await get_provider_rate_limit_cooldown_remaining(provider)
    if remaining is None:
        return None
    return RateLimitError(
        provider=provider,
        retry_after=max(1.0, math.ceil(remaining)),
        quota_details={"message": "Provider cooldown active"},
    )


def _build_completion_kwargs(
    model: str,
    provider: str,
    thinking_level: str | None,
    verbosity_level: str | None,
    prompt_cache_key: str | None,
) -> dict[str, object]:
    """Build provider-specific kwargs for adapter.complete."""
    extra_kwargs: dict[str, object] = {}
    if thinking_level:
        thinking_config = get_thinking_config(model, thinking_level, provider)
        if thinking_config:
            extra_kwargs.update(thinking_config)
        elif provider not in _UNSUPPORTED_NATIVE_THINKING_PROVIDERS:
            extra_kwargs["thinking_level"] = thinking_level
    capabilities = get_model_capabilities(model)
    if verbosity_level and (capabilities is None or capabilities.supports_verbosity):
        extra_kwargs["verbosity_level"] = verbosity_level
    if prompt_cache_key:
        extra_kwargs["prompt_cache_key"] = prompt_cache_key
    return extra_kwargs


async def _record_completion_error(
    provider: str,
    model: str,
    error: BaseException,
    start: float,
) -> None:
    """Record provider failure and rate-limit state for a completion error."""
    if isinstance(error, RateLimitError):
        await _RATE_LIMIT_BREAKER.trip(
            provider,
            cooldown_seconds=_resolve_retry_after_seconds(error),
            error_signature=f"rate_limit:{provider}",
        )
    record_provider_failure(provider, str(error), (time.monotonic() - start) * 1000)
    logger.warning("Model %s failed: %s", model, error)


async def _try_model(
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    verbosity_level: str | None = None,
    prompt_cache_key: str | None = None,
) -> tuple[object | None, BaseException | None]:
    """Attempt completion with a single model; return result and captured error."""
    provider = get_provider_for_model(model)
    cooldown_error = await _active_cooldown_error(provider)
    if cooldown_error is not None:
        logger.warning(
            "Skipping model %s because provider %s is cooling down for %.0fs",
            model,
            provider,
            cooldown_error.retry_after or 0,
        )
        return None, cooldown_error
    start = time.monotonic()
    try:
        adapter = get_adapter(provider)
        result = await adapter.complete(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            **_build_completion_kwargs(
                model,
                provider,
                thinking_level,
                verbosity_level,
                prompt_cache_key,
            ),
        )
        record_provider_success(provider, (time.monotonic() - start) * 1000)
        await _RATE_LIMIT_BREAKER.on_success(provider)
        return result, None
    except _COMPLETION_ERRORS as error:
        await _record_completion_error(provider, model, error, start)
        return None, error


async def _try_primary(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    verbosity_level: str | None = None,
    prompt_cache_key: str | None = None,
) -> CompletionResult | None:
    """Try the primary model; return CompletionResult or None on failure."""
    result, error = await _try_model(
        messages, agent.primary_model_id, temperature, max_tokens, tools, thinking_level, verbosity_level, prompt_cache_key
    )
    if result is None:
        logger.warning("Primary model %s failed for agent %s", agent.primary_model_id, agent.slug)
        return None
    return _completion_result(
        result=result,
        model_used=agent.primary_model_id,
        used_fallback=False,
        fallback_reason=_format_fallback_reason(error),
    )


async def _try_fallbacks(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    verbosity_level: str | None = None,
    blocked_providers: set[str] | None = None,
    prompt_cache_key: str | None = None,
) -> CompletionResult | None:
    """Try each fallback model in order; return first success or None."""
    blocked_providers = blocked_providers or set()
    for fallback_model in agent.fallback_models or []:
        fallback_provider = get_provider_for_model(fallback_model)
        if fallback_provider in blocked_providers:
            logger.info(
                "Skipping fallback model %s because provider %s is rate-limited",
                fallback_model,
                fallback_provider,
            )
            continue
        result, _error = await _try_model(
            messages, fallback_model, temperature, max_tokens, tools, thinking_level, verbosity_level, prompt_cache_key
        )
        if result is not None:
            logger.info("Agent %s used fallback model: %s", agent.slug, fallback_model)
            return _completion_result(result=result, model_used=fallback_model, used_fallback=True)
        if isinstance(_error, RateLimitError):
            blocked_providers.add(fallback_provider)
    return None


async def _try_escalation(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    verbosity_level: str | None = None,
    tried_models: set[str] | None = None,
    blocked_providers: set[str] | None = None,
    prompt_cache_key: str | None = None,
) -> CompletionResult | None:
    """Try the escalation model if configured and not already tried."""
    tried_models = tried_models or set()
    blocked_providers = blocked_providers or set()
    escalation = agent.escalation_model_id
    if not escalation or escalation in tried_models:
        return None
    escalation_provider = get_provider_for_model(escalation)
    if escalation_provider in blocked_providers:
        logger.info(
            "Skipping escalation model %s because provider %s is rate-limited",
            escalation,
            escalation_provider,
        )
        return None
    result, _error = await _try_model(
        messages, escalation, temperature, max_tokens, tools, thinking_level, verbosity_level, prompt_cache_key
    )
    if result is None:
        if isinstance(_error, RateLimitError):
            blocked_providers.add(escalation_provider)
        return None
    logger.info("Agent %s escalated to model: %s", agent.slug, escalation)
    return _completion_result(result=result, model_used=escalation, used_fallback=True)


def _completion_result(
    *,
    result: object,
    model_used: str,
    used_fallback: bool,
    fallback_reason: str | None = None,
) -> CompletionResult:
    """Build completion result payload."""
    return CompletionResult(
        result=result,
        model_used=model_used,
        used_fallback=used_fallback,
        fallback_reason=fallback_reason,
    )


def _raise_all_models_failed(
    agent: AgentDTO, primary_model: str, primary_reason: str | None
) -> NoReturn:
    """Raise ProviderError reporting exhausted model chain."""
    raise ProviderError(
        provider=get_provider_for_model(primary_model),
        message=f"All models failed for agent {agent.slug}: primary={primary_model}, "
        f"fallbacks={agent.fallback_models}, escalation={agent.escalation_model_id}, "
        f"primary_error={primary_reason}",
    )


async def _raise_primary_rate_limit(primary_error: RateLimitError) -> NoReturn:
    """Raise primary rate limit with refreshed cooldown window."""
    raise RateLimitError(
        provider=primary_error.provider,
        retry_after=max(
            1.0,
            math.ceil(
                await get_provider_rate_limit_cooldown_remaining(primary_error.provider)
                or _resolve_retry_after_seconds(primary_error)
            ),
        ),
        quota_details=primary_error.quota_details,
    )


async def complete_with_fallback(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None = None,
    tools: list[dict[str, object]] | None = None,
    thinking_level: str | None = None,
    primary_model_override: str | None = None,
    prompt_cache_key: str | None = None,
) -> CompletionResult:
    """Attempt completion using primary → fallbacks → escalation model chain.

    Args:
        primary_model_override: If set (e.g. from @mention), use this as the
            primary model instead of agent.primary_model_id.

    Raises:
        ProviderError: If all models (primary + fallbacks + escalation) fail
    """
    primary_model = primary_model_override or agent.primary_model_id
    verbosity_level = getattr(agent, "verbosity_level", None)
    blocked_providers: set[str] = set()

    result, primary_error = await _try_model(
        messages, primary_model, temperature, max_tokens, tools, thinking_level, verbosity_level, prompt_cache_key
    )
    if result is not None:
        return _completion_result(
            result=result,
            model_used=primary_model,
            used_fallback=primary_model != agent.primary_model_id,
        )
    logger.warning("Primary model %s failed for agent %s", primary_model, agent.slug)
    if isinstance(primary_error, RateLimitError):
        blocked_providers.add(primary_error.provider)
    primary_reason = _format_fallback_reason(primary_error)

    fallback_result = await _try_fallbacks(
        messages,
        agent,
        temperature,
        max_tokens,
        tools,
        thinking_level,
        verbosity_level,
        blocked_providers,
        prompt_cache_key,
    )
    if fallback_result is not None:
        fallback_result.fallback_reason = primary_reason
        return fallback_result

    tried_models = {primary_model} | set(agent.fallback_models or [])
    escalation_result = await _try_escalation(
        messages,
        agent,
        temperature,
        max_tokens,
        tools,
        thinking_level,
        verbosity_level,
        tried_models=tried_models,
        blocked_providers=blocked_providers,
        prompt_cache_key=prompt_cache_key,
    )
    if escalation_result is not None:
        escalation_result.fallback_reason = primary_reason
        return escalation_result

    if isinstance(primary_error, RateLimitError):
        await _raise_primary_rate_limit(primary_error)

    _raise_all_models_failed(agent, primary_model, primary_reason)


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
