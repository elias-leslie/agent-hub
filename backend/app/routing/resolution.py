"""Agent and model resolution.

Moved from ``app.api.complete.resolution`` per convergence-map.md C2.
Routing is now a peer of ``app.llm`` and ``app.memory``, not a sub-concern
of the HTTP completion package.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from app.services.adaptive_model_router import (
    RoutingContext,
    RoutingSelectionError,
    resolve_model_route,
)
from app.services.agent_dto import AgentDTO
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.agent_routing import (
    inject_agent_mandates,
    resolve_agent,
)
from app.services.agent_routing_models import MandateInjection, ResolvedAgent
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

ADHOC_AGENT_SLUG = "adhoc"


def _clean_weights(raw: dict[str, Any] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in (raw or {}).items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        result[str(key)] = min(1.0, weight)
    return result


def _list_or_empty(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _adhoc_context(request: CompletionRequest) -> dict[str, Any] | None:
    context = request.work_context.model_dump(exclude_none=True) if request.work_context else {}
    if request.adhoc_spec:
        context["adhoc_spec"] = request.adhoc_spec.model_dump(exclude_none=True)
    return context or None


def _adhoc_routing_context(
    request: CompletionRequest,
    request_hash: str,
) -> RoutingContext:
    spec = request.adhoc_spec
    judgment = spec.routing_judgment if spec and spec.routing_judgment else None
    preferences = spec.routing if spec and spec.routing else None
    requirements = _clean_weights(
        (judgment.capabilities if judgment else None)
        or (spec.capabilities if spec else None)
    )
    constraints: dict[str, Any] = {}
    if judgment:
        constraints.update(judgment.constraints or {})
    if spec:
        constraints.update(spec.constraints or {})
        if spec.tool_mode == "read_only":
            request.read_only = True
    exclude = [
        provider.lower()
        for provider in [
            *(_list_or_empty(request.routing_exclude_providers)),
            *(_list_or_empty(preferences.exclude_providers if preferences else None)),
        ]
    ]
    workload_profile = (
        request.workload_profile
        or (judgment.workload_profile if judgment else None)
        or (spec.workload_profile if spec else None)
    )
    risk_tier = (
        judgment.risk_tier if judgment and judgment.risk_tier else spec.risk_tier if spec else None
    )
    cost_preference = request.routing_cost_preference or (
        preferences.cost_preference if preferences else None
    )
    response_type = request.response_format.type if request.response_format else None
    return RoutingContext(
        request_id=request_hash,
        session_id=request.session_id,
        project_id=request.project_id,
        task_type=(spec.task_type if spec and spec.task_type else request.task_type),
        phase=request.phase,
        workload_profile=workload_profile,
        work_context=_adhoc_context(request),
        has_tools=bool(request.tools or request.execute_tools),
        requires_json=response_type == "json_object",
        has_vision_input=_messages_have_vision(request.messages),
        routing_mode_override="auto",
        canary_percent=0.0,
        adhoc=True,
        routing_requirements=requirements,
        routing_constraints=constraints,
        routing_risk_tier=risk_tier,
        routing_cost_preference=cost_preference,
        routing_exclude_providers=tuple(dict.fromkeys(exclude)),
    )


def _adhoc_agent() -> AgentDTO:
    now = datetime.now(UTC)
    return AgentDTO(
        id=0,
        slug=ADHOC_AGENT_SLUG,
        name="Adhoc",
        description="Runtime WorkSpec-driven execution",
        system_prompt="",
        primary_model_id="",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.7,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        memory_config={"enabled": False, "injection_enabled": False},
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=now,
        updated_at=now,
    )


def _render_adhoc_system_content(request: CompletionRequest) -> str:
    lines = [
        "<adhoc_execution_contract>",
        "You are a runtime WorkSpec-driven agent. Follow caller task/context exactly.",
        "Use tools when needed. Respect project scope, read-only flag, and explicit constraints.",
        "If required context, credentials, or tools are missing, stop with a concise blocker.",
        "Return changed files, checks run, important errors, and residual risk when applicable.",
        "</adhoc_execution_contract>",
    ]
    spec = request.adhoc_spec
    if not spec:
        return "\n".join(lines)
    lines.append("<adhoc_work_spec>")
    if spec.title:
        lines.append(f"title: {spec.title}")
    if spec.context:
        lines.append(f"context: {spec.context}")
    if spec.memories:
        lines.append(f"memories: {spec.memories}")
    if spec.expected_output:
        lines.append(f"expected_output: {spec.expected_output}")
    if spec.routing_judgment and spec.routing_judgment.rationale:
        lines.append(f"routing_rationale: {spec.routing_judgment.rationale}")
    lines.append("</adhoc_work_spec>")
    return "\n".join(lines)


async def _resolve_adhoc_agent_and_model(
    request: CompletionRequest,
    db: AsyncSession | None,
    request_hash: str,
) -> tuple[str, str, ResolvedAgent, MandateInjection, str]:
    from fastapi import HTTPException

    if not db:
        raise HTTPException(
            status_code=400,
            detail="Database connection required for adhoc routing.",
        )
    request.agent_slug = ADHOC_AGENT_SLUG
    if not request.memory_group_id:
        request.use_memory = False
    try:
        agent, route = await resolve_model_route(
            db,
            _adhoc_agent(),
            _adhoc_routing_context(request, request_hash),
        )
    except RoutingSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    provider = get_provider(agent.primary_model_id)
    resolved = ResolvedAgent(
        agent=agent,
        model=agent.primary_model_id,
        provider=provider,
        routing_mode=route.mode,
        workload_profile=route.workload_profile,
        routing_decision_id=route.decision_id,
        auto_candidate_model_id=route.auto_candidate_model_id,
        routing_canary_percent=route.canary_percent,
    )
    return (
        agent.primary_model_id,
        provider,
        resolved,
        MandateInjection(system_content=_render_adhoc_system_content(request), injected_uuids=[]),
        ADHOC_AGENT_SLUG,
    )


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

    if getattr(request, "adhoc", False):
        return await _resolve_adhoc_agent_and_model(request, db, request_hash)

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
                workload_profile=getattr(request, "workload_profile", None),
                work_context=work_context,
                has_tools=bool(getattr(request, "tools", None) or getattr(request, "execute_tools", False)),
                requires_json=response_type == "json_object",
                has_vision_input=_messages_have_vision(getattr(request, "messages", [])),
                routing_mode_override=getattr(request, "routing_mode_override", None),
                canary_percent=getattr(request, "routing_canary_percent", 0.0),
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
    from app.api.complete.helpers import parse_mention

    if request.messages:
        last_user_msg = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user_msg:
            mentioned_model, cleaned_content = parse_mention(last_user_msg.content)
            if mentioned_model:
                resolved_model = mentioned_model
                provider = get_provider(resolved_model)
                last_user_msg.content = cleaned_content
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
    "ADHOC_AGENT_SLUG",
    "apply_mention_override",
    "inject_agent_system_prompt",
    "resolve_agent_and_model",
]
