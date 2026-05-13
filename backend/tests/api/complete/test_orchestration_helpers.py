from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.complete.orchestration_helpers import execute_and_respond
from app.api.complete.types import CompletionInternalResult


@pytest.mark.asyncio
async def test_agentic_execute_and_respond_persists_result_before_response() -> None:
    request = SimpleNamespace(
        trace_id="trace-1",
        agent_slug="coder",
        response_format=None,
        thinking_level=None,
        auto_thinking=False,
        memory_group_id=None,
        external_id=None,
    )
    internal = CompletionInternalResult(
        content="done",
        model="kimi-code/kimi-for-coding",
        provider="kimi-code",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        session_id="sess-123",
        memory_uuids=[],
        cited_uuids=[],
        turns=2,
        tool_calls_count=1,
    )
    response = SimpleNamespace(session_id="sess-123")

    with (
        patch(
            "app.api.complete.orchestration_helpers.execute_completion",
            new_callable=AsyncMock,
            return_value=internal,
        ),
        patch(
            "app.api.complete.orchestration_helpers.process_completion_result",
            new_callable=AsyncMock,
            return_value=response,
        ) as process_result,
    ):
        result = await execute_and_respond(
            request=request,
            resolved_model="kimi-code/kimi-for-coding",
            provider="kimi-code",
            resolved_agent=None,
            messages_dict=[{"role": "user", "content": "run tool"}],
            all_messages=[],
            is_agentic=True,
            db=AsyncMock(),
            session=SimpleNamespace(),
            session_id="sess-123",
            client_id=None,
            source=None,
            skip_cache=False,
            ctx_info=None,
            memory_facts=0,
            loaded_uuids_in=[],
            agent_used="coder",
            is_new_session=True,
            http_request=None,
        )

    assert result is response
    process_result.assert_awaited_once()
    await_args = process_result.await_args
    assert await_args is not None
    assert await_args.args[0] is internal


@pytest.mark.asyncio
async def test_execute_and_respond_rolls_back_and_handles_cancelled_error() -> None:
    request = SimpleNamespace(
        trace_id=None,
        agent_slug="persona",
    )
    db = AsyncMock()

    with patch(
        "app.api.complete.orchestration_helpers.execute_completion",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError("sdk cancelled"),
    ), patch(
        "app.api.complete.orchestration_helpers.handle_completion_error",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=500, detail="Completion cancelled unexpectedly."),
    ) as handle_error, pytest.raises(HTTPException) as exc_info:
        await execute_and_respond(
            request=request,
            resolved_model="claude-sonnet-4-6",
            provider="claude",
            resolved_agent=None,
            messages_dict=[{"role": "user", "content": "hello"}],
            all_messages=[],
            is_agentic=True,
            db=db,
            session=None,
            session_id="sess-123",
            client_id=None,
            source=None,
            skip_cache=False,
            ctx_info=None,
            memory_facts=0,
            loaded_uuids_in=[],
            agent_used="persona",
            is_new_session=True,
            http_request=None,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Completion cancelled unexpectedly."
    db.rollback.assert_awaited_once()
    handle_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_completion_error_maps_cancelled_error_to_http_500() -> None:
    from app.api.complete.error_handlers import handle_completion_error

    with patch(
        "app.api.complete.error_handlers._notify_error",
        new_callable=AsyncMock,
    ) as notify_error, pytest.raises(HTTPException) as exc_info:
        await handle_completion_error(
            asyncio.CancelledError("sdk cancelled"),
            session_id="sess-123",
            db=AsyncMock(),
            agent_id="persona",
            model_used="claude-sonnet-4-6",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Completion cancelled unexpectedly."
    notify_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_guard_provider_cooldowns_raises_when_all_candidates_blocked() -> None:
    from app.api.complete.complete_orchestrator import _guard_provider_cooldowns

    request = SimpleNamespace(disable_agent_fallbacks=False)
    resolved_agent = SimpleNamespace(
        agent=SimpleNamespace(
            fallback_models=["claude-haiku-4-5"],
            escalation_model_id=None,
        )
    )

    with patch(
        "app.api.complete.complete_orchestrator.get_provider_rate_limit_cooldown_remaining",
        new=AsyncMock(return_value=45.2),
    ), pytest.raises(HTTPException) as exc_info:
        await _guard_provider_cooldowns(
            request=request,
            provider="claude",
            resolved_agent=resolved_agent,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == (
        "Provider cooldown active (claude 46s). Wait 46s before retrying the same provider."
    )


@pytest.mark.asyncio
async def test_guard_provider_cooldowns_allows_request_when_alternate_provider_is_available() -> None:
    from app.api.complete.complete_orchestrator import _guard_provider_cooldowns

    request = SimpleNamespace(disable_agent_fallbacks=False)
    resolved_agent = SimpleNamespace(
        agent=SimpleNamespace(
            fallback_models=["gemini-3-flash-preview"],
            escalation_model_id=None,
        )
    )

    async def fake_cooldown(provider: str) -> float | None:
        return 30.0 if provider == "claude" else None

    with patch(
        "app.api.complete.complete_orchestrator.get_provider_rate_limit_cooldown_remaining",
        new=AsyncMock(side_effect=fake_cooldown),
    ):
        await _guard_provider_cooldowns(
            request=request,
            provider="claude",
            resolved_agent=resolved_agent,
        )
