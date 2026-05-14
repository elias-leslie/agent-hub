"""Completion logic for Agent Routing Service."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import TYPE_CHECKING, Any, NoReturn

from sqlalchemy.ext.asyncio import AsyncSession

from app.routing.registry import is_workload_provider, list_providers
from app.services.agent_dto import AgentDTO
from app.services.circuit_breaker import CircuitBreakerManager
from app.services.llm_errors import (
    ProviderError,
    RateLimitError,
)
from app.services.llm_messages import (
    Message,
)
from app.services.model_runtime_health import (
    classify_runtime_failure,
    record_model_runtime_failure,
    record_model_runtime_success,
)

from .agent_routing_models import FallbackCompletionResult
from .agent_routing_utils import get_provider_for_model

if TYPE_CHECKING:
    from app.api.complete.types import CompletionInternalResult

logger = logging.getLogger(__name__)

_COMPLETION_ERRORS = (RateLimitError, ProviderError, RuntimeError, asyncio.TimeoutError)
_DEFAULT_RATE_LIMIT_COOLDOWN = 60.0
_UNSUPPORTED_NATIVE_THINKING_PROVIDERS = {"codex", "openai", "openrouter", "zhipu", "minimax", "xai"}
_RATE_LIMIT_BREAKER = CircuitBreakerManager(list_providers())


def record_provider_failure(_provider: str, _error: str, _latency_ms: float | None = None) -> None:
    """Compatibility hook after deleting the legacy active health prober."""


def record_provider_success(_provider: str, _latency_ms: float | None = None) -> None:
    """Compatibility hook after deleting the legacy active health prober."""


def _format_fallback_reason(error: BaseException | None) -> str | None:
    """Return a compact, user-visible explanation for a fallback trigger."""
    if error is None:
        return None
    return f"{type(error).__name__}: {error}"


def _error_from_terminal_result(result: CompletionInternalResult) -> RuntimeError | None:
    """Return an error when the provider encoded failure in the terminal message."""
    if result.finish_reason not in ("error", "aborted"):
        return None
    message = result.message.error_message or f"Provider returned finish_reason={result.finish_reason}"
    return RuntimeError(message)


def _resolve_retry_after_seconds(error: RateLimitError) -> float:
    """Return the cooldown window to enforce for a provider rate limit."""
    retry_after = error.retry_after
    if retry_after is None or retry_after <= 0:
        return _DEFAULT_RATE_LIMIT_COOLDOWN
    return float(retry_after)


def _runtime_failure_cooldown(error: BaseException) -> float | None:
    if isinstance(error, RateLimitError):
        return _resolve_retry_after_seconds(error)
    return classify_runtime_failure(error).cooldown_seconds


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


def _messages_as_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate adapter ``Message`` rows to ``{role, content}`` wire dicts."""
    return [{"role": m.role, "content": m.content} for m in messages]


async def _record_completion_error(
    provider: str,
    model: str,
    error: BaseException,
    start: float,
    db: AsyncSession | None = None,
) -> None:
    """Record provider failure and rate-limit state for a completion error."""
    cooldown_seconds = _runtime_failure_cooldown(error)
    if cooldown_seconds is not None:
        await _RATE_LIMIT_BREAKER.trip(
            provider,
            cooldown_seconds=cooldown_seconds,
            error_signature=f"runtime_failure:{provider}:{type(error).__name__}",
        )
    await record_model_runtime_failure(db, model_id=model, provider=provider, error=error)
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
    db: AsyncSession | None = None,
) -> tuple[CompletionInternalResult | None, BaseException | None]:
    """Attempt completion with a single model; return result and captured error.

    Routes each attempt through the new pipeline by calling
    :func:`backend.app.api.complete.core.complete_internal` with ``db=None``.
    The fallback iteration, cooldown logic, and circuit-breaker bookkeeping
    are unchanged.
    """
    from app.api.complete.core import complete_internal

    provider = get_provider_for_model(model)
    if not is_workload_provider(provider):
        return None, ProviderError(
            provider=provider,
            message=(
                "Claude/Anthropic models are catalog references and external "
                "Claude Code TUI only; Agent Hub workloads must use a routable provider."
            ),
            status_code=400,
        )
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
        internal = await complete_internal(
            messages=_messages_as_dicts(messages),
            model=model,
            provider=provider,
            temperature=temperature,
            project_id="",
            db=None,
            session_id=prompt_cache_key,
            tools=tools,
            thinking_level=_thinking_level_for_provider(provider, thinking_level),
            max_turns=1,
            execute_tools=False,
        )
        terminal_error = _error_from_terminal_result(internal)
        if terminal_error is not None:
            raise terminal_error
        record_provider_success(provider, (time.monotonic() - start) * 1000)
        await record_model_runtime_success(db, model_id=model, provider=provider)
        await _RATE_LIMIT_BREAKER.on_success(provider)
        return internal, None
    except _COMPLETION_ERRORS as error:
        await _record_completion_error(provider, model, error, start, db)
        return None, error


def _thinking_level_for_provider(provider: str, thinking_level: str | None) -> str | None:
    if provider in _UNSUPPORTED_NATIVE_THINKING_PROVIDERS:
        return None
    return thinking_level


async def _try_primary(
    messages: list[Message],
    agent: AgentDTO,
    temperature: float,
    max_tokens: int | None,
    tools: list[dict[str, object]] | None,
    thinking_level: str | None,
    verbosity_level: str | None = None,
    prompt_cache_key: str | None = None,
) -> FallbackCompletionResult | None:
    """Try the primary model; return fallback result or None on failure."""
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
    db: AsyncSession | None = None,
) -> FallbackCompletionResult | None:
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
            messages,
            fallback_model,
            temperature,
            max_tokens,
            tools,
            thinking_level,
            verbosity_level,
            prompt_cache_key,
            db,
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
    db: AsyncSession | None = None,
) -> FallbackCompletionResult | None:
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
        messages,
        escalation,
        temperature,
        max_tokens,
        tools,
        thinking_level,
        verbosity_level,
        prompt_cache_key,
        db,
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
) -> FallbackCompletionResult:
    """Build completion result payload."""
    return FallbackCompletionResult(
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
    db: AsyncSession | None = None,
) -> FallbackCompletionResult:
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
        messages,
        primary_model,
        temperature,
        max_tokens,
        tools,
        thinking_level,
        verbosity_level,
        prompt_cache_key,
        db,
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
        db,
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
        db=db,
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
