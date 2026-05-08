"""Tests for completion agent resolution memory-config behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.request_schemas import (
    AdhocWorkSpec,
    CompletionRequest,
    MessageInput,
    RoutingJudgment,
    RoutingPreferences,
)
from app.api.complete.resolution import resolve_agent_and_model
from app.services.agent_dto import AgentDTO


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        agent_slug="note-titler",
        include_roles=None,
        project_id="agent-hub",
        task_type="chat",
        model=None,
    )


def _resolved_agent(memory_config: dict[str, object] | None) -> SimpleNamespace:
    return SimpleNamespace(
        agent=SimpleNamespace(slug="note-titler", memory_config=memory_config),
        model="codex/gpt-5.4",
        provider="codex",
    )


def _await_kwargs(mock: AsyncMock) -> dict[str, object]:
    assert mock.await_args is not None
    return dict(mock.await_args.kwargs)


def _routed_agent() -> AgentDTO:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return AgentDTO(
        id=0,
        slug="adhoc",
        name="Adhoc",
        description="Runtime",
        system_prompt="",
        primary_model_id="kimi-code/kimi-for-coding",
        fallback_models=["minimax/MiniMax-M2.7"],
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


@pytest.mark.asyncio
async def test_resolve_agent_and_model_preserves_agent_prompt_when_injection_disabled() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"injection_enabled": False}),
        ),
        patch(
            "app.api.complete.resolution.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(system_content="agent", injected_uuids=[]),
        ) as mock_inject,
    ):
        _, _, _, mandate_injection, agent_used = await resolve_agent_and_model(
            request,
            db,
            "hash-1",
        )

    assert mandate_injection is not None
    assert agent_used == "note-titler"
    kwargs = _await_kwargs(mock_inject)
    assert kwargs["include_mandates"] is False
    assert kwargs["include_guardrails"] is False


@pytest.mark.asyncio
async def test_resolve_agent_and_model_disables_optional_runtime_layers_when_enabled_false() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"enabled": False, "injection_enabled": True}),
        ),
        patch(
            "app.api.complete.resolution.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(system_content="agent", injected_uuids=[]),
        ) as mock_inject,
    ):
        _, _, _, mandate_injection, _ = await resolve_agent_and_model(
            request,
            db,
            "hash-2",
        )

    assert mandate_injection is not None
    kwargs = _await_kwargs(mock_inject)
    assert kwargs["include_mandates"] is False
    assert kwargs["include_guardrails"] is False


@pytest.mark.asyncio
async def test_resolve_agent_and_model_disables_mandate_runtime_prompts_when_include_mandates_disabled() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"include_mandates": False, "include_guardrails": True}),
        ),
        patch(
            "app.api.complete.resolution.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(system_content="agent", injected_uuids=[]),
        ) as mock_inject,
    ):
        _, _, _, mandate_injection, _ = await resolve_agent_and_model(
            request,
            db,
            "hash-3",
        )

    assert mandate_injection is not None
    kwargs = _await_kwargs(mock_inject)
    assert kwargs["include_mandates"] is False
    assert kwargs["include_guardrails"] is True


@pytest.mark.asyncio
async def test_resolve_agent_and_model_disables_guardrail_runtime_prompts_when_include_guardrails_disabled() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"include_mandates": True, "include_guardrails": False}),
        ),
        patch(
            "app.api.complete.resolution.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(system_content="agent", injected_uuids=[]),
        ) as mock_inject,
    ):
        _, _, _, mandate_injection, _ = await resolve_agent_and_model(
            request,
            db,
            "hash-4",
        )

    assert mandate_injection is not None
    kwargs = _await_kwargs(mock_inject)
    assert kwargs["include_mandates"] is True
    assert kwargs["include_guardrails"] is False


@pytest.mark.asyncio
async def test_resolve_agent_and_model_supports_structured_adhoc_routing() -> None:
    request = CompletionRequest(
        project_id="agent-hub",
        messages=[MessageInput(role="user", content="Inspect current state")],
        adhoc=True,
        execute_tools=True,
        adhoc_spec=AdhocWorkSpec(
            title="Inspect",
            routing_judgment=RoutingJudgment(
                workload_profile="coding_impl",
                risk_tier="normal",
                capabilities={"coding": 0.9, "tool_use": 0.8},
                constraints={"tool_use": True},
                rationale="Repo work needs tools.",
            ),
            routing=RoutingPreferences(
                exclude_providers=["codex"],
                cost_preference="low_cost",
            ),
        ),
    )
    route = SimpleNamespace(
        mode="auto",
        workload_profile="coding_impl",
        decision_id="decision-1",
        auto_candidate_model_id="kimi-code/kimi-for-coding",
        canary_percent=0,
    )

    with patch(
        "app.api.complete.resolution.resolve_model_route",
        new_callable=AsyncMock,
        return_value=(_routed_agent(), route),
    ) as mock_route:
        resolved_model, provider, resolved_agent, mandate, agent_used = await resolve_agent_and_model(
            request,
            AsyncMock(),
            "hash-adhoc",
        )

    assert mock_route.await_args is not None
    routing_context = mock_route.await_args.args[2]
    assert resolved_model == "kimi-code/kimi-for-coding"
    assert provider == "kimi-code"
    assert resolved_agent is not None
    assert mandate is not None
    assert agent_used == "adhoc"
    assert request.agent_slug == "adhoc"
    assert request.use_memory is False
    assert routing_context.adhoc is True
    assert routing_context.workload_profile == "coding_impl"
    assert routing_context.routing_requirements == {"coding": 0.9, "tool_use": 0.8}
    assert routing_context.routing_constraints == {"tool_use": True}
    assert routing_context.routing_exclude_providers == ("codex",)
    assert routing_context.routing_cost_preference == "low_cost"
