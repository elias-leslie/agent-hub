"""Completion orchestration logic."""

from __future__ import annotations

import hashlib
import logging
import math
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.async_dispatch import dispatch_async_completion
from app.api.complete.handlers import build_cached_completion_response
from app.api.complete.orchestration_helpers import build_session_and_messages, execute_and_respond
from app.api.complete.schemas import CompletionRequest, CompletionResponse
from app.api.complete.streaming_handlers import handle_streaming_request
from app.api.complete.validation import (
    validate_agent_slug,
    validate_audio_capability,
    validate_project_access,
)
from app.routing.registry import get_provider_for_model, is_workload_provider
from app.routing.resolution import (
    apply_mention_override,
    resolve_agent_and_model,
)
from app.services.agent_routing_completion import get_provider_rate_limit_cooldown_remaining

if TYPE_CHECKING:
    from fastapi import Request

    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def _reference_only_provider_error(model: str, provider: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": "provider_not_routable",
            "provider": provider,
            "model": model,
            "message": (
                "Claude/Anthropic models are catalog references and external "
                "Claude Code TUI only; Agent Hub workloads must use a routable provider."
            ),
        },
    )


def _guard_workload_routing(
    *,
    request: CompletionRequest,
    model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
) -> None:
    """Reject reference-only providers before execution or fallback handling."""
    if not is_workload_provider(provider):
        raise _reference_only_provider_error(model, provider)

    if not resolved_agent or request.disable_agent_fallbacks:
        return

    for fallback_model in resolved_agent.agent.fallback_models or []:
        fallback_provider = get_provider_for_model(fallback_model)
        if not is_workload_provider(fallback_provider):
            raise _reference_only_provider_error(fallback_model, fallback_provider)

    escalation_model = resolved_agent.agent.escalation_model_id
    if escalation_model:
        escalation_provider = get_provider_for_model(escalation_model)
        if not is_workload_provider(escalation_provider):
            raise _reference_only_provider_error(escalation_model, escalation_provider)


async def _guard_provider_cooldowns(
    *,
    request: CompletionRequest,
    provider: str,
    resolved_agent: ResolvedAgent | None,
) -> None:
    """Reject early when every candidate provider is cooling down after rate limits."""
    candidate_providers = {provider}
    if resolved_agent and not request.disable_agent_fallbacks:
        candidate_providers.update(
            get_provider_for_model(model_id)
            for model_id in (resolved_agent.agent.fallback_models or [])
        )
        if resolved_agent.agent.escalation_model_id:
            candidate_providers.add(get_provider_for_model(resolved_agent.agent.escalation_model_id))

    cooldowns: dict[str, float] = {}
    for candidate in candidate_providers:
        remaining = await get_provider_rate_limit_cooldown_remaining(candidate)
        if remaining is not None:
            cooldowns[candidate] = remaining

    if cooldowns and len(cooldowns) == len(candidate_providers):
        max_wait = max(1, math.ceil(max(cooldowns.values())))
        detail = ", ".join(
            f"{name} {max(1, math.ceil(wait))}s"
            for name, wait in sorted(cooldowns.items())
        )
        raise HTTPException(
            status_code=429,
            detail=f"Provider cooldown active ({detail}). Wait {max_wait}s before retrying the same provider.",
        )


async def _validate_and_resolve(
    request: CompletionRequest, http_request: Request, db: AsyncSession | None
) -> tuple[str, str | None, str | None, str, str, ResolvedAgent | None, AgentMandateInjection | None, str | None]:
    """Validate request and resolve model/agent; return resolution tuple."""
    await validate_agent_slug(request, db)
    validate_project_access(request, getattr(http_request.state, "allowed_projects", None))
    if request.async_execution and request.stream:
        raise HTTPException(status_code=400, detail="Cannot combine async_execution with stream mode.")
    rh = hashlib.md5(
        f"{request.model or request.agent_slug}:{len(request.messages)}".encode()
    ).hexdigest()[:8]
    logger.debug(
        f"DEBUG[{rh}] complete() called: model={request.model or 'via-agent'}, "
        f"agent_slug={request.agent_slug}, messages={len(request.messages)}"
    )
    client_id = getattr(http_request.state, "client_id", None)
    request_source = getattr(http_request.state, "request_source", None)
    resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used = (
        await resolve_agent_and_model(request, db, rh)
    )
    http_request.state.agent_slug = request.agent_slug
    pre_override_model = resolved_model
    resolved_model, provider = apply_mention_override(request, resolved_model)
    if request.agent_slug and resolved_model != pre_override_model:
        logger.debug(
            "DEBUG[%s] Agent routing override: %s -> %s (requested via mention)",
            rh,
            request.agent_slug,
            resolved_model,
        )
    validate_audio_capability(request, resolved_model)
    _guard_workload_routing(
        request=request,
        model=resolved_model,
        provider=provider,
        resolved_agent=resolved_agent,
    )
    http_request.state.resolved_model = resolved_model
    return rh, client_id, request_source, resolved_model, provider, resolved_agent, agent_mandate_injection, agent_used


async def _check_quotas(
    request: CompletionRequest, resolved_agent: ResolvedAgent | None, db: AsyncSession | None
) -> None:
    """Enforce per-agent execution quotas and per-project cost budget."""
    if resolved_agent and resolved_agent.agent:
        from app.services.quota import QuotaExceededError, check_request_quota, check_token_quota

        agent_dto = resolved_agent.agent
        try:
            await check_request_quota(agent_dto.slug, agent_dto.hourly_request_limit)
            await check_token_quota(agent_dto.slug, agent_dto.daily_token_budget)
        except QuotaExceededError as e:
            raise HTTPException(status_code=429, detail=str(e)) from e

    if request.project_id:
        from app.services.project_budget import check_project_budget

        budget_result = await check_project_budget(request.project_id, db)
        if not budget_result.allowed:
            raise HTTPException(status_code=429, detail=f"Project budget exceeded: {budget_result.reason}")


async def orchestrate_completion(
    request: CompletionRequest,
    http_request: Request,
    skip_cache: bool,
    db: AsyncSession | None,
) -> CompletionResponse | StreamingResponse | JSONResponse:
    """Orchestrate a completion request through the entire pipeline."""
    rh, client_id, source, resolved_model, provider, resolved_agent, mandate, agent_used = (
        await _validate_and_resolve(request, http_request, db)
    )
    await _check_quotas(request, resolved_agent, db)
    await _guard_provider_cooldowns(
        request=request,
        provider=provider,
        resolved_agent=resolved_agent,
    )
    if request.stream:
        return await handle_streaming_request(
            request=request, resolved_model=resolved_model, provider=provider,
            resolved_agent=resolved_agent, agent_mandate_injection=mandate,
            agent_used=agent_used, model_used=None, fallback_used=False, db=db,
            client_id=client_id, request_source=source,
        )
    is_agentic, session_id, session, is_new_session, all_messages, messages_dict, memory_facts, loaded_uuids, ctx_info, cached = (
        await build_session_and_messages(request, provider, resolved_model, resolved_agent, mandate, db, client_id, source, skip_cache)
    )
    if cached:
        response = await build_cached_completion_response(
            cached, db, session, session_id, request, resolved_model,
            ctx_info, memory_facts, is_new_session=is_new_session,
        )
        return response
    if is_agentic and request.async_execution:
        return await dispatch_async_completion(
            request=request, messages_dict=messages_dict, resolved_model=resolved_model,
            provider=provider, session_id=session_id, resolved_agent=resolved_agent,
            all_messages=all_messages, skip_cache=skip_cache,
            client_id=client_id, request_source=source,
        )
    if is_agentic:
        logger.debug(
            f"DEBUG[{rh}] Agentic mode: max_turns={request.max_turns}, "
            f"execute_tools={request.execute_tools}, working_dir={request.working_dir}"
        )
    return await execute_and_respond(
        request, resolved_model, provider, resolved_agent, messages_dict, all_messages,
        is_agentic, db, session, session_id, client_id, source, skip_cache,
        ctx_info, memory_facts, loaded_uuids, agent_used, is_new_session,
        http_request=http_request,
    )
