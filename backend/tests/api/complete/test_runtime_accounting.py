"""Runtime accounting across the real tool-loop/completion persistence seams."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.handler_helpers import save_and_track
from app.api.complete.orchestrator import run_completion, run_completion_stream
from app.api.complete.schemas import CompletionRequest, MessageInput
from app.api.complete.sse_writer import SseWriter
from app.api.complete.streaming import _emit_events, _persist_and_build_done_sse
from app.api.complete.types import CompletionInternalResult
from app.constants.catalog import MODEL_CATALOG_BY_ID
from app.llm.event_stream import create_assistant_message_event_stream
from app.llm.model_resolver import resolve_llm_model
from app.llm.types import (
    AssistantMessage,
    Context,
    DoneEvent,
    ErrorEvent,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from app.llm.utils.outcomes import ProviderOutcome, outcome_details, record_outcome
from app.services.token_counter import estimate_usage_cost
from tests.api.stream_test_support import make_stream_ctx, patched_done_persistence
from tests.model_ids import DEFAULT_GEMINI_MODEL, GEMINI_2_5_FLASH


def _messages(*, error: bool = False) -> list[AssistantMessage]:
    return [
        AssistantMessage(
            content=[ToolCall(id="call", name="echo", arguments={})],
            api="google-generative-ai", provider="gemini", model=GEMINI_2_5_FLASH,
            usage=Usage(input=100, output=10, cache_read=20, cache_write=30, total_tokens=160),
            stop_reason="toolUse", timestamp=0,
        ),
        AssistantMessage(
            content=[TextContent(text="done")],
            api="google-generative-ai", provider="gemini", model=DEFAULT_GEMINI_MODEL,
            usage=Usage(input=200, output=20, cache_read=40, cache_write=60, total_tokens=320),
            stop_reason="error" if error else "stop", timestamp=0,
            error_message="provider failed" if error else None,
        ),
    ]


async def _tool(call: ToolCall) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call.id, tool_name=call.name, content=[TextContent(text="ok")],
        is_error=False, timestamp=0,
    )


def _streams(messages: list[AssistantMessage]):
    streams = []
    for message in messages:
        stream = create_assistant_message_event_stream()
        if message.stop_reason == "error":
            stream.push(ErrorEvent(reason="error", error=message))
        else:
            stream.push(DoneEvent(reason=message.stop_reason, message=message))
        streams.append(stream)
    return streams


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [False, True])
async def test_sync_tool_loop_retains_each_calls_usage_without_mutating_context(error: bool) -> None:
    messages = _messages(error=error)
    context = Context(messages=[UserMessage(content="go", timestamp=0)])
    with patch("app.llm.tool_loop.stream_simple", side_effect=_streams(messages)):
        result = await run_completion(
            resolve_llm_model(DEFAULT_GEMINI_MODEL, "gemini"), context,
            execute_tools=True, run_tool=_tool,
        )
    assert result.message.usage == Usage(
        input=300, output=30, cache_read=60, cache_write=90, total_tokens=480,
    )
    assert result.turns == 2
    assert [message.usage.input for message in context.messages if isinstance(message, AssistantMessage)] == [100, 200]
    assert result.usage_messages == messages


@pytest.mark.asyncio
async def test_stream_tool_loop_done_persists_cumulative_usage_and_per_model_costs() -> None:
    import json

    messages = _messages()
    ctx = make_stream_ctx("runtime-usage", model=DEFAULT_GEMINI_MODEL)
    with (
        patch("app.llm.tool_loop.stream_simple", side_effect=_streams(messages)),
        patched_done_persistence() as mocks,
    ):
        chunks = [json.loads(chunk.removeprefix("data: ")) async for chunk in _emit_events(
            run_completion_stream(
                resolve_llm_model(DEFAULT_GEMINI_MODEL, "gemini"), Context(messages=[]),
                execute_tools=True, run_tool=_tool,
            ), SseWriter(session_id=ctx.session_id), ctx, [""], tool_loop_active=True,
        )]
    done = chunks[-1]
    assert (done["input_tokens"], done["output_tokens"], done["cache_read_tokens"], done["cache_write_tokens"]) == (300, 30, 60, 90)
    assert [call.args[2] for call in mocks.log_stream_cost.await_args_list] == [GEMINI_2_5_FLASH, DEFAULT_GEMINI_MODEL]
    expected = sum(_expected_cost(message) for message in messages)
    assert done["cost_usd"] == pytest.approx(expected)
    assert sum(call.args[3] for call in mocks.log_stream_cost.await_args_list) == pytest.approx(expected)


def _expected_cost(message: AssistantMessage) -> float:
    price = MODEL_CATALOG_BY_ID[message.model].cost
    usage = message.usage
    return (usage.input * price.input_per_m + usage.output * price.output_per_m
            + usage.cache_read * (price.cache_read_per_million or 0)
            + usage.cache_write * (price.cache_write_per_million or 0)) / 1e6


@pytest.mark.asyncio
async def test_save_and_track_prices_disjoint_cache_usage() -> None:
    message = _messages()[1]
    request = CompletionRequest(messages=[MessageInput(role="user", content="go")], project_id="agent-hub")
    session = SimpleNamespace(
        status="active", model=DEFAULT_GEMINI_MODEL, provider="gemini",
        models_used=[], providers_used=[], provider_metadata={},
    )
    with (
        patch("app.api.complete.handler_helpers.save_events", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.persist_execution_observability", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.api.complete.handler_helpers.publish_complete", new_callable=AsyncMock),
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock),
    ):
        await save_and_track(
            AsyncMock(), session, "usage", request, CompletionInternalResult(message=message),
            DEFAULT_GEMINI_MODEL, False,
        )
    assert log_usage.await_args is not None
    assert log_usage.await_args.args[5] == pytest.approx(_expected_cost(message))
    assert log_usage.await_args.kwargs["cache_read_tokens"] == 40
    assert log_usage.await_args.kwargs["cache_write_tokens"] == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [False, True])
async def test_sync_tool_loop_persists_each_calls_model_and_usage(error: bool) -> None:
    messages = _messages(error=error)
    with patch("app.llm.tool_loop.stream_simple", side_effect=_streams(messages)):
        orchestration = await run_completion(
            resolve_llm_model(DEFAULT_GEMINI_MODEL, "gemini"), Context(messages=[]),
            execute_tools=True, run_tool=_tool,
        )
    result = CompletionInternalResult(
        message=orchestration.message, usage_messages=orchestration.usage_messages,
    )
    session = SimpleNamespace(
        status="active", model=DEFAULT_GEMINI_MODEL, provider="gemini",
        models_used=[], providers_used=[], provider_metadata={},
    )
    with (
        patch("app.api.complete.handler_helpers.save_events", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.persist_execution_observability", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.api.complete.handler_helpers.publish_complete", new_callable=AsyncMock) as complete,
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock) as budget,
    ):
        await save_and_track(
            AsyncMock(), session, "usage", CompletionRequest(
                messages=[MessageInput(role="user", content="go")], project_id="agent-hub",
            ), result, DEFAULT_GEMINI_MODEL, False,
            execution_status="error" if error else "success", execution_error=result.error,
        )
    assert [call.args[2:5] for call in log_usage.await_args_list] == [
        (GEMINI_2_5_FLASH, 100, 10), (DEFAULT_GEMINI_MODEL, 200, 20),
    ]
    total_cost = sum(_expected_cost(message) for message in messages)
    assert complete.await_args is not None
    assert budget.await_args is not None
    assert complete.await_args.args[1:] == pytest.approx((300, 30, total_cost))
    assert budget.await_args.args[1] == pytest.approx(total_cost)


@pytest.mark.asyncio
async def test_stream_tool_loop_records_usage_before_a_later_error() -> None:
    messages = _messages(error=True)
    ctx = make_stream_ctx("runtime-error", model=DEFAULT_GEMINI_MODEL)
    with (
        patch("app.llm.tool_loop.stream_simple", side_effect=_streams(messages)),
        patched_done_persistence() as mocks,
    ):
        chunks = [chunk async for chunk in _emit_events(
            run_completion_stream(
                resolve_llm_model(DEFAULT_GEMINI_MODEL, "gemini"), Context(messages=[]),
                execute_tools=True, run_tool=_tool,
            ), SseWriter(session_id=ctx.session_id), ctx, [""], tool_loop_active=True,
        )]
    assert '"type": "error"' in chunks[-1]
    assert [call.args[1].usage.input for call in mocks.log_stream_cost.await_args_list] == [100, 200]
    assert [call.args[2] for call in mocks.log_stream_cost.await_args_list] == [GEMINI_2_5_FLASH, DEFAULT_GEMINI_MODEL]


def test_runtime_cache_cost_uses_disjoint_buckets_and_write_rate() -> None:
    price = SimpleNamespace(
        input_per_m=0.75, output_per_m=3.75,
        cache_read_per_million=0.075, cache_write_per_million=1.5,
    )
    with patch("app.services.token_counter._get_model_entry", return_value=SimpleNamespace(cost=price)):
        cost = estimate_usage_cost(3282, 782, DEFAULT_GEMINI_MODEL, cache_read_tokens=8166)
        assert cost.total_cost_usd == pytest.approx(0.00600645)
        cache_only = estimate_usage_cost(0, 0, DEFAULT_GEMINI_MODEL, cache_read_tokens=20, cache_write_tokens=30)
        assert cache_only.total_cost_usd == pytest.approx((20 * 0.075 + 30 * 1.5) / 1e6)


@pytest.mark.asyncio
@pytest.mark.parametrize("all_failed", [False, True])
async def test_agentic_fallback_persists_failed_attempt_usage_before_retry(all_failed: bool) -> None:
    from app.api.complete.complete_execution import _run_with_agentic_fallback

    messages = _messages(error=all_failed)
    messages[0].stop_reason = "error"
    messages[0].error_message = "primary failed"
    results = [CompletionInternalResult(
        message=message, finish_reason=message.stop_reason, session_id="retry",
    ) for message in messages]
    db = AsyncMock()
    ctx = make_stream_ctx("retry", model=DEFAULT_GEMINI_MODEL)
    with (
        patch("app.api.complete.complete_execution._run_internal", new=AsyncMock(side_effect=results)),
        patch("app.routing.availability.route_unavailable_reason", new=AsyncMock(return_value=None)),
        patch("app.api.complete.complete_execution.record_model_runtime_failure", new_callable=AsyncMock),
        patch("app.api.complete.complete_execution.record_model_runtime_success", new_callable=AsyncMock),
        patch("app.services.context_tracker.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock) as budget,
    ):
        call = _run_with_agentic_fallback(
            CompletionRequest(messages=[MessageInput(role="user", content="go")], project_id="agent-hub"),
            GEMINI_2_5_FLASH, "gemini", SimpleNamespace(agent=SimpleNamespace(fallback_models=[DEFAULT_GEMINI_MODEL])),
            [], db, ctx.session_id, None, None, None, None, None, False,
        )
        if all_failed:
            with pytest.raises(RuntimeError, match="primary failed"):
                await call
        else:
            result = await call
            assert result is results[1]
    failed_messages = messages if all_failed else messages[:1]
    assert [call.args[2:5] for call in log_usage.await_args_list] == [
        (message.model, message.usage.input, message.usage.output) for message in failed_messages
    ]
    assert sum(call.args[5] for call in log_usage.await_args_list) == pytest.approx(
        sum(_expected_cost(message) for message in failed_messages)
    )
    assert db.commit.await_count == len(failed_messages)
    assert sum(call.args[1] for call in budget.await_args_list) == pytest.approx(
        sum(_expected_cost(message) for message in failed_messages)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("all_failed", [False, True])
@pytest.mark.parametrize("session_found", [False, True])
async def test_non_agentic_fallback_persists_failed_result_usage(all_failed: bool, session_found: bool) -> None:
    from app.services.agent_routing_completion import complete_with_fallback
    from app.services.llm_errors import ProviderError
    from app.services.llm_messages import Message

    messages = _messages(error=all_failed)
    messages[0].stop_reason = "error"
    messages[0].error_message = "primary failed"
    results = [CompletionInternalResult(
        message=message, finish_reason=message.stop_reason, session_id="retry",
    ) for message in messages]
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id="retry", project_id="agent-hub", agent_slug="coder") if session_found else None
    agent = SimpleNamespace(
        primary_model_id=GEMINI_2_5_FLASH, fallback_models=[DEFAULT_GEMINI_MODEL],
        escalation_model_id=None, slug="coder", verbosity_level=None,
    )
    with (
        patch("app.api.complete.core.complete_internal", new=AsyncMock(side_effect=results)) as complete,
        patch("app.services.agent_routing_completion.route_unavailable_reason", new=AsyncMock(return_value=None)),
        patch("app.services.agent_routing_completion._active_cooldown_error", new=AsyncMock(return_value=None)),
        patch("app.services.agent_routing_completion._RATE_LIMIT_BREAKER", new=AsyncMock()),
        patch("app.services.agent_routing_completion.record_model_runtime_failure", new_callable=AsyncMock),
        patch("app.services.agent_routing_completion.record_model_runtime_success", new_callable=AsyncMock),
        patch("app.services.context_tracker.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock) as budget,
        patch("app.services.quota.record_token_usage", new_callable=AsyncMock) as quota,
    ):
        call = complete_with_fallback(
            [Message(role="user", content="go")], agent, 0.0,
            prompt_cache_key="retry", db=db,
        )
        if all_failed:
            with pytest.raises(ProviderError, match="All models failed"):
                await call
        else:
            result = await call
            assert result.result is results[1]
            assert result.used_fallback is True
        assert [call.kwargs["model"] for call in complete.await_args_list] == [GEMINI_2_5_FLASH, DEFAULT_GEMINI_MODEL]
    failed_messages = (messages if all_failed else messages[:1]) if session_found else []
    assert [call.args[2:5] for call in log_usage.await_args_list] == [
        (message.model, message.usage.input, message.usage.output) for message in failed_messages
    ]
    assert sum(call.args[5] for call in log_usage.await_args_list) == pytest.approx(
        sum(_expected_cost(message) for message in failed_messages)
    )
    assert db.commit.await_count == len(failed_messages)
    assert sum(call.args[1] for call in budget.await_args_list) == pytest.approx(
        sum(_expected_cost(message) for message in failed_messages)
    )
    assert sum(call.args[1] for call in quota.await_args_list) == sum(
        message.usage.input + message.usage.output for message in failed_messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model,provider", [(DEFAULT_GEMINI_MODEL, "gemini"), ("claude-sonnet-5-5", "claude")])
async def test_response_cache_hits_save_history_without_rebilling_provider_usage(model: str, provider: str) -> None:
    from app.api.complete.handlers import build_cached_completion_response
    from app.services.response_cache.models import CachedResponse

    cached = CachedResponse(
        content="cached answer", model=model, provider=provider,
        input_tokens=100, output_tokens=20, finish_reason="stop",
        cached_at="2026-10-22T12:00:00Z", cache_key="fixture",
    )
    db = AsyncMock()
    session = SimpleNamespace(
        status="active", model=model, provider=provider,
        models_used=[], providers_used=[], provider_metadata={},
    )
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="go")],
        project_id="agent-hub", agent_slug="coder",
    )
    with (
        patch("app.api.complete.event_helpers.store_message_event", new_callable=AsyncMock) as store_message,
        patch("app.api.complete.handler_helpers.persist_execution_observability", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.api.complete.handler_helpers.publish_complete", new_callable=AsyncMock) as publish,
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock) as budget,
        patch("app.services.quota.record_token_usage", new_callable=AsyncMock) as quota,
    ):
        for _ in range(2):
            response = await build_cached_completion_response(
                cached, db, session, "cached-session", request, model, None, 0,
            )
            assert response.content == "cached answer"
            assert response.from_cache is True
            assert (response.usage.input_tokens, response.usage.output_tokens) == (100, 20)
    assert [call.kwargs["role"] for call in store_message.await_args_list] == ["user", "assistant", "user", "assistant"]
    assert [call.kwargs["content"] for call in store_message.await_args_list] == ["go", "cached answer", "go", "cached answer"]
    assert all(call.args[3] == 0.0 for call in publish.await_args_list)
    log_usage.assert_not_awaited()
    budget.assert_not_awaited()
    quota.assert_not_awaited()
    assert session.health_detail == "completed"
    assert db.commit.await_count >= 2


def _served_message(*, requested: str, reported: str | None, outcome: ProviderOutcome | None = None) -> AssistantMessage:
    message = AssistantMessage(
        content=[TextContent(text="done")], api="google-generative-ai", provider="gemini", model=requested,
        usage=Usage(input=100, output=10, total_tokens=110), stop_reason="stop", timestamp=0,
        response_model=reported,
    )
    if outcome is not None:
        record_outcome(message, outcome)
    return message


async def _save_and_track(message: AssistantMessage, requested: str) -> tuple[SimpleNamespace, AsyncMock, AsyncMock]:
    request = CompletionRequest(messages=[MessageInput(role="user", content="go")], project_id="agent-hub")
    session = SimpleNamespace(
        status="active", model=requested, provider="gemini", models_used=[], providers_used=[], provider_metadata={},
    )
    with (
        patch("app.api.complete.handler_helpers.save_events", new_callable=AsyncMock) as save_events,
        patch("app.api.complete.handler_helpers.persist_execution_observability", new_callable=AsyncMock),
        patch("app.api.complete.handler_helpers.log_token_usage", new_callable=AsyncMock) as log_usage,
        patch("app.api.complete.handler_helpers.publish_complete", new_callable=AsyncMock),
        patch("app.services.project_budget.record_project_cost", new_callable=AsyncMock),
    ):
        await save_and_track(
            AsyncMock(), session, "served", request, CompletionInternalResult(message=message), requested, False,
        )
    return session, save_events, log_usage


@pytest.mark.asyncio
async def test_served_catalog_model_lands_in_events_cost_logs_and_session_metadata() -> None:
    outcome = ProviderOutcome(kind="substituted", requested_model=DEFAULT_GEMINI_MODEL, served_model=GEMINI_2_5_FLASH)
    message = _served_message(requested=DEFAULT_GEMINI_MODEL, reported=GEMINI_2_5_FLASH, outcome=outcome)

    session, save_events, log_usage = await _save_and_track(message, DEFAULT_GEMINI_MODEL)

    saved, logged = save_events.await_args, log_usage.await_args
    assert saved is not None and logged is not None
    assert saved.args[6] == GEMINI_2_5_FLASH
    assert saved.kwargs["usage"] == {"provider_outcome": outcome_details(outcome)}
    assert logged.args[2] == GEMINI_2_5_FLASH
    assert logged.args[5] == pytest.approx(
        estimate_usage_cost(100, 10, GEMINI_2_5_FLASH).total_cost_usd
    )
    assert session.provider_metadata["requested_model"] == DEFAULT_GEMINI_MODEL
    assert session.provider_metadata["served_model"] == GEMINI_2_5_FLASH


@pytest.mark.asyncio
async def test_unpriced_served_model_is_shown_on_the_event_but_cost_keeps_the_route_identity() -> None:
    message = _served_message(requested=DEFAULT_GEMINI_MODEL, reported="aggregator-alias-7b")

    _, save_events, log_usage = await _save_and_track(message, DEFAULT_GEMINI_MODEL)

    saved, logged = save_events.await_args, log_usage.await_args
    assert saved is not None and logged is not None
    assert saved.args[6] == "aggregator-alias-7b"
    assert saved.kwargs["usage"] is None
    assert logged.args[2] == DEFAULT_GEMINI_MODEL


@pytest.mark.asyncio
async def test_matching_or_snapshot_response_model_changes_nothing() -> None:
    message = _served_message(requested=DEFAULT_GEMINI_MODEL, reported=f"{DEFAULT_GEMINI_MODEL}-2026-04-23")

    session, save_events, log_usage = await _save_and_track(message, DEFAULT_GEMINI_MODEL)

    saved, logged = save_events.await_args, log_usage.await_args
    assert saved is not None and logged is not None
    assert saved.args[6] == DEFAULT_GEMINI_MODEL
    assert logged.args[2] == DEFAULT_GEMINI_MODEL
    assert "served_model" not in session.provider_metadata


@pytest.mark.asyncio
async def test_stream_done_saves_the_served_model_and_outcome() -> None:
    outcome = ProviderOutcome(kind="refused", requested_model=DEFAULT_GEMINI_MODEL, category="content_filter")
    message = _served_message(requested=DEFAULT_GEMINI_MODEL, reported=GEMINI_2_5_FLASH, outcome=outcome)
    ctx = make_stream_ctx("s-served", model=DEFAULT_GEMINI_MODEL, agent_used="chat")

    with patched_done_persistence() as mocks:
        await _persist_and_build_done_sse(
            writer=SseWriter(session_id="s-served"), ctx=ctx, message=message, accumulated_content="ok",
        )

    call = mocks.save_messages_to_db.await_args
    assert call is not None
    kwargs = call.kwargs
    assert kwargs["model"] == GEMINI_2_5_FLASH
    assert kwargs["usage"] == {"provider_outcome": outcome_details(outcome)}
