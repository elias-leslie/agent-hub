"""Tests for completion agent resolution memory-config behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routing.resolution import resolve_agent_and_model


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        agent_slug="note-titler",
        include_roles=None,
        prompt_mode=None,
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


@pytest.mark.asyncio
async def test_resolve_agent_and_model_preserves_agent_prompt_when_injection_disabled() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.routing.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"injection_enabled": False}),
        ),
        patch(
            "app.routing.resolution.inject_agent_mandates",
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
            "app.routing.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"enabled": False, "injection_enabled": True}),
        ),
        patch(
            "app.routing.resolution.inject_agent_mandates",
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
            "app.routing.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"include_mandates": False, "include_guardrails": True}),
        ),
        patch(
            "app.routing.resolution.inject_agent_mandates",
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
            "app.routing.resolution.resolve_agent",
            new_callable=AsyncMock,
            return_value=_resolved_agent({"include_mandates": True, "include_guardrails": False}),
        ),
        patch(
            "app.routing.resolution.inject_agent_mandates",
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
