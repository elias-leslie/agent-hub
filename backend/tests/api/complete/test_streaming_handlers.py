from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import StreamingResponse

from app.api.complete.request_schemas import (
    CompletionRequest,
    MessageInput,
    SourceMetadata,
)
from app.api.complete.streaming_handlers import (
    _build_sse_response,
    _compact_streaming_context,
    _inject_streaming_memory,
    _setup_streaming_session,
    handle_streaming_request,
)
from app.services.llm_messages import Message
from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.context_injector_ops import inject_memory_block
from app.services.memory.context_resilience import CanonicalContextInjectionFailed
from app.services.turn_runs import registry as turn_registry


@pytest.mark.asyncio
async def test_build_sse_response_forwards_loaded_tools_and_requested_max_turns() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hello")],
        project_id="agent-hub",
        execute_tools=True,
        max_turns=37,
    )
    loaded_tools = [{"name": "search_web", "description": "Search", "input_schema": {"type": "object"}}]

    async def fake_stream_completion(**kwargs):
        assert kwargs["tools"] == loaded_tools
        assert kwargs["max_tool_turns"] == 37
        yield "data: [DONE]\n\n"

    with (
        patch(
            "app.api.complete.streaming_handlers.provision_standard_tools",
            return_value=type("Provisioned", (), {"loaded_tools": loaded_tools})(),
        ),
        patch(
            "app.api.complete.streaming_handlers.stream_completion",
            side_effect=fake_stream_completion,
        ) as mock_stream_completion,
    ):
        response = _build_sse_response(
            messages=[],
            resolved_model="codex/gpt-5.4",
            provider="codex",
            request=request,
            session_id="sess-1",
            thinking_level=None,
            agent_used="persona",
            model_used="codex/gpt-5.4",
            fallback_used=False,
            db=None,
            is_new_session=True,
            tools=loaded_tools,
        )

    assert isinstance(response, StreamingResponse)
    assert mock_stream_completion.call_args.kwargs["max_tool_turns"] == 37
    run = turn_registry.get("sess-1")
    assert run is not None
    await run.finished.wait()


@pytest.mark.asyncio
async def test_build_sse_response_forwards_source_metadata() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hello")],
        project_id="agent-hub",
        source_metadata=SourceMetadata(
            transport="web",
            surface="work_chats",
            pane_id="pane-1",
            source_client="agent-hub/work-chats",
        ),
    )

    async def fake_stream_completion(**_kwargs):
        yield "data: [DONE]\n\n"

    with patch(
        "app.api.complete.streaming_handlers.stream_completion",
        side_effect=fake_stream_completion,
    ) as mock_stream_completion:
        response = _build_sse_response(
            messages=[],
            resolved_model="codex/gpt-5.4",
            provider="codex",
            request=request,
            session_id="sess-1",
            thinking_level=None,
            agent_used="persona",
            model_used="codex/gpt-5.4",
            fallback_used=False,
            db=None,
            is_new_session=True,
            tools=None,
        )

    assert isinstance(response, StreamingResponse)
    assert mock_stream_completion.call_args.kwargs["source_metadata"] == {
        "transport": "web",
        "surface": "work_chats",
        "pane_id": "pane-1",
        "source_client": "agent-hub/work-chats",
    }
    run = turn_registry.get("sess-1")
    assert run is not None
    await run.finished.wait()


@pytest.mark.asyncio
async def test_compact_streaming_context_replaces_messages_when_compacted() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="old"),
    ]
    compacted = [
        {"role": "system", "content": "system"},
        {"role": "system", "content": "compact summary"},
        {"role": "user", "content": "latest"},
    ]

    with patch(
        "app.api.complete.streaming_handlers.compact_context_if_needed",
        new_callable=AsyncMock,
        return_value=(compacted, True),
    ) as mock_compact:
        result = await _compact_streaming_context(
            messages,
            "claude-sonnet-5-5",
            "sess-1",
            AsyncMock(),
        )

    mock_compact.assert_awaited_once()
    assert [m.content for m in result] == ["system", "compact summary", "latest"]


@pytest.mark.asyncio
async def test_setup_streaming_session_does_not_persist_adaptive_metadata() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="do work")],
        project_id="agent-hub",
        agent_slug="coder",
    )
    session = type("Session", (), {"id": "sess-1", "provider_metadata": None})()
    resolved_agent = type("ResolvedAgent", (), {})()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.streaming_handlers.get_or_create_session",
            new_callable=AsyncMock,
            return_value=(session, [], True),
        ),
        patch(
            "app.api.complete.streaming_handlers.bind_request_context",
            new_callable=AsyncMock,
        ),
        patch("app.api.complete.streaming_handlers.mark_session_execution_start"),
        patch(
            "app.api.complete.streaming_handlers.publish_session_start",
            new_callable=AsyncMock,
        ),
    ):
        session_id, _messages, is_new = await _setup_streaming_session(
            request,
            provider="kimi-code",
            resolved_model="kimi-code/kimi-for-coding",
            resolved_agent=resolved_agent,
            db=db,
            client_id="client-1",
            request_source="pytest",
        )

    assert session_id == "sess-1"
    assert is_new is True
    assert session.provider_metadata is None


@pytest.mark.asyncio
async def test_agent_stream_forces_canonical_prompts_when_prompt_mode_none() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="do work")],
        project_id="agent-hub",
        agent_slug="coder",
        prompt_mode="none",
        use_memory=False,
    )
    resolved_agent = type(
        "ResolvedAgent",
        (),
        {"agent": type("Agent", (), {"memory_config": {}, "slug": "coder"})()},
    )()
    original = [Message(role="user", content="do work")]
    injected_dicts = inject_memory_block(
        [{"role": "user", "content": "do work"}],
        "## Safety Directive\nStay safe.",
    )

    with patch(
        "app.api.complete.streaming_handlers.inject_progressive_context",
        new=AsyncMock(return_value=(injected_dicts, ProgressiveContext())),
    ) as inject_mock:
        result = await _inject_streaming_memory(
            request,
            original,
            "sess-1",
            resolved_agent,
            None,
        )

    inject_mock.assert_awaited_once()
    assert inject_mock.await_args is not None
    assert inject_mock.await_args.kwargs["include_prompts"] is True
    assert inject_mock.await_args.kwargs["include_memories"] is False
    assert result[0].role == "system"


@pytest.mark.asyncio
async def test_agent_stream_aborts_before_response_without_verified_context() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="do work")],
        project_id="agent-hub",
        agent_slug="coder",
        prompt_mode="none",
        max_turns=2,
    )
    resolved_agent = type("ResolvedAgent", (), {})()
    build_response = AsyncMock()
    raw_messages = [Message(role="user", content="do work")]

    with (
        patch(
            "app.api.complete.streaming_handlers._setup_streaming_session",
            new=AsyncMock(return_value=("sess-1", [], True)),
        ),
        patch(
            "app.api.complete.streaming_handlers._inject_streaming_memory",
            new=AsyncMock(return_value=raw_messages),
        ),
        patch(
            "app.api.complete.streaming_handlers._compact_streaming_context",
            new=AsyncMock(return_value=raw_messages),
        ),
        patch(
            "app.api.complete.streaming_handlers._build_sse_response",
            new=build_response,
        ),
        pytest.raises(
            CanonicalContextInjectionFailed,
            match="hash-verified Agent Hub canonical context envelope",
        ),
    ):
        await handle_streaming_request(
            request=request,
            resolved_model="kimi-code/kimi-for-coding",
            provider="kimi-code",
            resolved_agent=resolved_agent,
            agent_mandate_injection=None,
            agent_used="coder",
            model_used=None,
            fallback_used=False,
            db=None,
            client_id=None,
            request_source="pytest",
        )

    build_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_streaming_turn_does_not_hold_the_request_connection() -> None:
    """The turn runs for minutes on its own sessions; the request's pooled connection goes back before it starts."""
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hi")], project_id="agent-hub", prompt_mode="none", max_turns=1, use_memory=False
    )
    raw_messages = [Message(role="user", content="hi")]
    db = AsyncMock()
    order: list[str] = []
    db.rollback.side_effect = lambda: order.append("rollback")

    def build(*_args: object, **_kwargs: object) -> str:
        order.append("turn started")
        return "response"

    with (
        patch("app.api.complete.streaming_handlers._setup_streaming_session", new=AsyncMock(return_value=("s", [], True))),
        patch("app.api.complete.streaming_handlers._inject_streaming_memory", new=AsyncMock(return_value=raw_messages)),
        patch("app.api.complete.streaming_handlers._compact_streaming_context", new=AsyncMock(return_value=raw_messages)),
        patch("app.api.complete.streaming_handlers._build_sse_response", new=build),
    ):
        result = await handle_streaming_request(
            request=request, resolved_model="local/x", provider="local", resolved_agent=None,
            agent_mandate_injection=None, agent_used=None, model_used=None, fallback_used=False,
            db=db, client_id=None, request_source="pytest",
        )

    assert result == "response"
    assert order == ["rollback", "turn started"]


@pytest.mark.asyncio
async def test_a_session_runs_one_turn_at_a_time_and_a_cancelled_turn_is_waited_out() -> None:
    import asyncio

    from fastapi import HTTPException

    from app.api.complete.streaming_handlers import _claim_session_turn
    from app.services.turn_runs import DONE_CHUNK

    gate = asyncio.Event()

    async def source():
        await gate.wait()
        yield 'data: {"type":"done","seq":1}\n\n'
        yield DONE_CHUNK

    run = turn_registry.start("busy-session", source(), persist=False)
    await _claim_session_turn(None)
    await _claim_session_turn("another-session")
    with pytest.raises(HTTPException) as busy:
        await _claim_session_turn("busy-session")
    assert busy.value.status_code == 409
    assert busy.value.detail["error"] == "turn_running"
    assert busy.value.detail["details"] == {"session_id": "busy-session", "turn_id": run.turn_id}

    turn_registry.note_cancel_requested("busy-session")
    waiting = asyncio.create_task(_claim_session_turn("busy-session"))
    await asyncio.sleep(0.01)
    assert not waiting.done()
    gate.set()
    await asyncio.wait_for(waiting, 2)
    assert not run.running
