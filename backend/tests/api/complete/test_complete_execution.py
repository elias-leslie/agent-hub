"""Tests for completion execution fallback metadata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import CompletionResult, ProviderError
from app.adapters.types import Message
from app.api.complete.execution import execute_with_fallback
from app.api.complete.types import CompletionInternalResult


@pytest.mark.asyncio
async def test_execute_with_fallback_attaches_primary_failure_reason_to_result() -> None:
    resolved_agent = SimpleNamespace(
        model="claude-sonnet-4-6",
        agent=SimpleNamespace(
            slug="refactor",
            primary_model_id="claude-sonnet-4-6",
            fallback_models=["codex/gpt-5.4"],
            temperature=0.0,
            verbosity_level=None,
        ),
    )
    adapter_result = CompletionResult(
        content="ok",
        model="codex/gpt-5.4",
        provider="codex",
        input_tokens=1,
        output_tokens=1,
    )
    fallback_result = SimpleNamespace(
        result=adapter_result,
        model_used="codex/gpt-5.4",
        used_fallback=True,
        fallback_reason="ProviderError: claude timed out",
    )

    with patch(
        "app.api.complete.execution.complete_with_fallback",
        new=AsyncMock(return_value=fallback_result),
    ):
        result, model_used, fallback_used = await execute_with_fallback(
            messages_for_adapter=[Message(role="user", content="refactor")],
            resolved_agent=resolved_agent,
            tools_api=None,
            thinking_level=None,
        )

    assert result is adapter_result
    assert model_used == "codex/gpt-5.4"
    assert fallback_used is True
    assert result.fallback_reason == "ProviderError: claude timed out"


@pytest.mark.asyncio
async def test_execute_with_fallback_does_not_mark_explicit_override_as_fallback() -> None:
    resolved_agent = SimpleNamespace(
        model="codex/gpt-5.4",
        agent=SimpleNamespace(
            slug="persona",
            primary_model_id="codex/gpt-5.4",
            fallback_models=["claude-sonnet-4-6"],
            temperature=0.0,
            verbosity_level=None,
        ),
    )
    adapter_result = CompletionResult(
        content="ok",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=1,
        output_tokens=1,
    )
    direct_override_result = SimpleNamespace(
        result=adapter_result,
        model_used="claude-sonnet-4-6",
        used_fallback=True,
        fallback_reason=None,
    )

    with patch(
        "app.api.complete.execution.complete_with_fallback",
        new=AsyncMock(return_value=direct_override_result),
    ):
        result, model_used, fallback_used = await execute_with_fallback(
            messages_for_adapter=[Message(role="user", content="hi")],
            resolved_agent=resolved_agent,
            tools_api=None,
            thinking_level=None,
            resolved_model="claude-sonnet-4-6",
        )

    assert result is adapter_result
    assert model_used == "claude-sonnet-4-6"
    assert fallback_used is False
    assert not hasattr(result, "fallback_reason")


@pytest.mark.asyncio
async def test_execute_with_fallback_preserves_primary_failure_reason_on_later_success() -> None:
    req = SimpleNamespace(
        temperature=0.0,
        project_id="agent-hub",
        external_id=None,
        memory_group_id=None,
        enable_caching=True,
        cache_ttl=None,
        enable_programmatic_tools=False,
        container_id=None,
        messages=[],
        max_turns=2,
        execute_tools=True,
        working_dir=None,
        trace_id=None,
        task_type=None,
        phase=None,
        agent_slug="refactor",
    )
    agent = SimpleNamespace(agent=SimpleNamespace(fallback_models=["codex/gpt-5.4", "gemini-2.5-pro"]))
    success = CompletionInternalResult(
        content="done",
        model="gemini-2.5-pro",
        provider="gemini",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )
    side_effect = [
        ProviderError(provider="claude", message="primary blew up"),
        ProviderError(provider="codex", message="first fallback blew up"),
        success,
    ]

    async def fake_run_internal(*args, **kwargs):
        value = side_effect.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    with patch("app.api.complete.complete_execution._run_internal", new=AsyncMock(side_effect=fake_run_internal)):
        from app.api.complete.complete_execution import _run_with_agentic_fallback

        result = await _run_with_agentic_fallback(
            req=req,
            primary_model="claude-sonnet-4-6",
            provider="claude",
            agent=agent,
            msgs=[],
            db=AsyncMock(),
            sid="sess-1",
            client_id=None,
            source=None,
            thinking=None,
            tools=None,
            fmt=None,
            skip_cache=False,
        )

    assert result.model_used == "gemini-2.5-pro"
    assert result.fallback_used is True
    assert result.fallback_reason == "ProviderError: primary blew up"
