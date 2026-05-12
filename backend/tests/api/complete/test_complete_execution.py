"""Tests for completion execution fallback metadata."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.execution import build_agentic_response, execute_with_fallback
from app.api.complete.types import CompletionInternalResult
from app.services.llm_errors import ProviderError
from app.services.llm_messages import Message


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
    adapter_result = CompletionInternalResult(
        content="ok",
        model="codex/gpt-5.4",
        provider="codex",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-fallback",
        memory_uuids=[],
        cited_uuids=[],
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
    adapter_result = CompletionInternalResult(
        content="ok",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-direct",
        memory_uuids=[],
        cited_uuids=[],
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
    assert result.fallback_reason is None


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


@pytest.mark.asyncio
async def test_agentic_fallback_times_out_quiet_primary_model_turn() -> None:
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
        agent_slug="explorer",
    )
    agent = SimpleNamespace(
        agent=SimpleNamespace(
            fallback_models=["codex/gpt-5.4"],
            timeout_seconds=0.01,
        )
    )
    success = CompletionInternalResult(
        content="done",
        model="codex/gpt-5.4",
        provider="codex",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )
    calls: list[str] = []

    async def fake_run_internal(*args, **kwargs):
        model_id = args[1]
        calls.append(model_id)
        if model_id == "nvidia/kimi-k2.6":
            await asyncio.sleep(10)
        return success

    with patch(
        "app.api.complete.complete_execution._run_internal",
        new=AsyncMock(side_effect=fake_run_internal),
    ):
        from app.api.complete.complete_execution import _run_with_agentic_fallback

        result = await _run_with_agentic_fallback(
            req=req,
            primary_model="nvidia/kimi-k2.6",
            provider="nvidia",
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

    assert calls == ["nvidia/kimi-k2.6", "codex/gpt-5.4"]
    assert result.model_used == "codex/gpt-5.4"
    assert result.fallback_used is True
    assert result.fallback_reason == "TimeoutError: Agentic model turn timed out after 0.01s"


@pytest.mark.asyncio
async def test_dispatch_db_bypasses_agentic_fallback_chain_when_disabled() -> None:
    from app.api.complete.complete_execution import _dispatch_db

    req = SimpleNamespace(
        disable_agent_fallbacks=True,
    )
    agent = SimpleNamespace(agent=SimpleNamespace(fallback_models=["codex/gpt-5.4"]))

    direct_result = CompletionInternalResult(
        content="done",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )

    with patch(
        "app.api.complete.complete_execution._run_internal",
        new=AsyncMock(return_value=direct_result),
    ) as run_internal, patch(
        "app.api.complete.complete_execution._run_with_agentic_fallback",
        new=AsyncMock(),
    ) as run_with_fallback:
        result = await _dispatch_db(
            req=req,
            model="claude-sonnet-4-6",
            provider="claude",
            agent=agent,
            msgs=[],
            db=AsyncMock(),
            is_agentic=True,
            sid="sess-1",
            client_id=None,
            source=None,
            thinking=None,
            tools=None,
            fmt=None,
            skip_cache=False,
        )

    assert result is direct_result
    run_internal.assert_awaited_once()
    run_with_fallback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_memory", [True, False])
async def test_run_internal_forwards_use_memory_to_complete_internal(use_memory: bool) -> None:
    from app.api.complete.complete_execution import _run_internal

    req = SimpleNamespace(
        temperature=0.0,
        project_id="agent-hub",
        external_id=None,
        parent_session_id=None,
        agent_slug="persona",
        use_memory=use_memory,
        memory_group_id="project:agent-hub",
        enable_caching=False,
        cache_ttl=None,
        enable_programmatic_tools=False,
        container_id=None,
        messages=[],
        max_turns=3,
        execute_tools=True,
        working_dir="/tmp/agent-hub",
        trace_id=None,
        task_type=None,
        phase=None,
    )
    internal_result = CompletionInternalResult(
        content="done",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )

    with patch(
        "app.api.complete.complete_execution.complete_internal",
        new=AsyncMock(return_value=internal_result),
    ) as mock_complete_internal:
        result = await _run_internal(
            req=req,
            model="claude-sonnet-4-6",
            provider="claude",
            agent=None,
            msgs=[{"role": "user", "content": "hi"}],
            db=AsyncMock(),
            sid="sess-1",
            client_id=None,
            source=None,
            thinking=None,
            tools=None,
            fmt=None,
            skip_cache=False,
            is_agentic=True,
        )

    assert result is internal_result
    await_args = mock_complete_internal.await_args
    assert await_args is not None
    assert await_args.kwargs["use_memory"] is use_memory


@pytest.mark.asyncio
async def test_execute_completion_with_db_non_agentic_uses_single_turn_path() -> None:
    from app.api.complete.complete_execution import execute_completion

    request = SimpleNamespace(
        temperature=0.0,
        tools=None,
        response_format=None,
        thinking_level=None,
        auto_thinking=False,
        disable_agent_fallbacks=False,
        enable_programmatic_tools=False,
        enable_caching=False,
        cache_ttl=None,
        container_id=None,
    )
    adapter_result = CompletionInternalResult(
        content="ok",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=5,
        output_tokens=7,
        finish_reason="stop",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
    )

    with patch(
        "app.api.complete.complete_execution.execute_without_db",
        new=AsyncMock(return_value=(adapter_result, "claude-sonnet-4-6")),
    ) as execute_without_db, patch(
        "app.api.complete.complete_execution._dispatch_db",
        new=AsyncMock(),
    ) as dispatch_db:
        result = await execute_completion(
            request=request,
            resolved_model="claude-sonnet-4-6",
            provider="claude",
            resolved_agent=None,
            messages_dict=[{"role": "user", "content": "hi"}],
            all_messages=[Message(role="user", content="hi")],
            is_agentic=False,
            db=AsyncMock(),
            session_id="sess-1",
            client_id=None,
            request_source=None,
            skip_cache=False,
        )

    assert result == (adapter_result, "claude-sonnet-4-6", False, [], "sess-1", None)
    execute_without_db.assert_awaited_once()
    dispatch_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_internal_passes_parent_session_id_to_complete_internal() -> None:
    from app.api.complete.complete_execution import _run_internal

    request = SimpleNamespace(
        temperature=0.0,
        project_id="agent-hub",
        external_id=None,
        parent_session_id="persona-root",
        agent_slug="planner",
        use_memory=True,
        messages=[{"role": "user", "content": "plan"}],
        memory_group_id=None,
        enable_caching=False,
        cache_ttl=None,
        enable_programmatic_tools=False,
        container_id=None,
        max_turns=2,
        execute_tools=True,
        working_dir=None,
        trace_id=None,
        task_type=None,
        phase="planning",
    )
    internal_result = CompletionInternalResult(
        content="plan",
        model="codex/gpt-5.4",
        provider="codex",
        input_tokens=3,
        output_tokens=2,
        finish_reason="stop",
        session_id="sess-plan",
        memory_uuids=[],
        cited_uuids=[],
    )

    with patch(
        "app.api.complete.complete_execution.complete_internal",
        new=AsyncMock(return_value=internal_result),
    ) as complete_internal:
        result = await _run_internal(
            req=request,
            model="codex/gpt-5.4",
            provider="codex",
            agent=None,
            msgs=[{"role": "user", "content": "plan"}],
            db=AsyncMock(),
            sid="sess-parent",
            client_id=None,
            source="agent-hub-dashboard",
            thinking=None,
            tools=None,
            fmt=None,
            skip_cache=False,
            is_agentic=True,
        )

    assert result is internal_result
    complete_internal.assert_awaited_once()
    assert complete_internal.await_args is not None
    assert complete_internal.await_args.kwargs["parent_session_id"] == "persona-root"


def _execute_without_db_request() -> SimpleNamespace:
    return SimpleNamespace(
        temperature=0.0,
        project_id="proj-1",
        external_id=None,
        parent_session_id=None,
        agent_slug=None,
        enable_caching=False,
        cache_ttl="ephemeral",
        enable_programmatic_tools=False,
        container_id=None,
        working_dir=None,
        trace_id=None,
        task_type=None,
        phase=None,
        current_branch=None,
    )


def _internal_result(model: str, provider: str) -> CompletionInternalResult:
    return CompletionInternalResult(
        content="ok",
        model=model,
        provider=provider,
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="ephemeral:sess-x",
        memory_uuids=[],
        cited_uuids=[],
    )


@pytest.mark.asyncio
async def test_execute_without_db_routes_through_complete_internal() -> None:
    from app.api.complete.execution import execute_without_db

    request = _execute_without_db_request()
    internal = _internal_result("claude-sonnet-4-6", "claude")

    with patch(
        "app.api.complete.core.complete_internal",
        new=AsyncMock(return_value=internal),
    ) as ci:
        result, model_used = await execute_without_db(
            messages_for_adapter=[Message(role="user", content="hi")],
            resolved_model="claude-sonnet-4-6",
            provider="claude",
            request=request,
            thinking_level=None,
            tools_api=None,
            response_format_dict=None,
        )

    assert model_used == "claude-sonnet-4-6"
    assert result.content == "ok"
    assert result.model == "claude-sonnet-4-6"
    ci.assert_awaited_once()
    assert ci.await_args is not None
    kwargs = ci.await_args.kwargs
    assert kwargs["db"] is None
    assert kwargs["execute_tools"] is False
    assert kwargs["max_turns"] == 1


@pytest.mark.asyncio
async def test_execute_without_db_forwards_session_id_and_thinking_level() -> None:
    from app.api.complete.execution import execute_without_db

    request = _execute_without_db_request()
    internal = _internal_result("xai/grok-4.20-multi-agent", "xai")

    with patch(
        "app.api.complete.core.complete_internal",
        new=AsyncMock(return_value=internal),
    ) as ci:
        await execute_without_db(
            messages_for_adapter=[Message(role="user", content="hi")],
            resolved_model="xai/grok-4.20-multi-agent",
            provider="xai",
            request=request,
            thinking_level="high",
            tools_api=None,
            response_format_dict=None,
            session_id="sess-99",
        )

    assert ci.await_args is not None
    kwargs = ci.await_args.kwargs
    assert kwargs["session_id"] == "sess-99"
    assert kwargs["thinking_level"] == "high"


@pytest.mark.asyncio
async def test_execute_without_db_propagates_provider_errors() -> None:
    from app.api.complete.execution import execute_without_db

    request = _execute_without_db_request()

    with (
        patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(side_effect=ProviderError(provider="claude", message="boom")),
        ),
        pytest.raises(ProviderError),
    ):
        await execute_without_db(
            messages_for_adapter=[Message(role="user", content="hi")],
            resolved_model="claude-sonnet-4-6",
            provider="claude",
            request=request,
            thinking_level=None,
            tools_api=None,
            response_format_dict=None,
        )


def test_build_agentic_response_preserves_internal_finish_reason_on_success() -> None:
    internal_result = CompletionInternalResult(
        content="done",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=1,
        output_tokens=2,
        finish_reason="max_turns",
        session_id="sess-1",
        memory_uuids=[],
        cited_uuids=[],
        status="success",
        turns=3,
        tool_calls_count=5,
    )

    response = build_agentic_response(
        internal_result=internal_result,
        context_usage_info=None,
        thinking_level=None,
        agent_used="debugger",
        fallback_used=False,
        trace_id=None,
    )

    assert response.finish_reason == "max_turns"
