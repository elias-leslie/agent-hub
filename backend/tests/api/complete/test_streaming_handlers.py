from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import StreamingResponse

from app.adapters.base import Message
from app.api.complete.request_schemas import (
    AdhocWorkSpec,
    CompletionRequest,
    MessageInput,
    SourceMetadata,
)
from app.api.complete.streaming_handlers import (
    _build_sse_response,
    _compact_streaming_context,
    _setup_streaming_session,
)


def test_build_sse_response_forwards_loaded_tools_and_requested_max_turns() -> None:
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
            routing_mode=None,
            workload_profile=None,
            routing_decision_id=None,
            auto_candidate_model_id=None,
            routing_canary_percent=None,
            db=None,
            is_new_session=True,
            tools=loaded_tools,
        )

    assert isinstance(response, StreamingResponse)
    assert mock_stream_completion.call_args.kwargs["max_tool_turns"] == 37


def test_build_sse_response_forwards_source_metadata() -> None:
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
            routing_mode=None,
            workload_profile=None,
            routing_decision_id=None,
            auto_candidate_model_id=None,
            routing_canary_percent=None,
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
            "claude-sonnet-4-6",
            "sess-1",
            AsyncMock(),
        )

    mock_compact.assert_awaited_once()
    assert [m.content for m in result] == ["system", "compact summary", "latest"]


@pytest.mark.asyncio
async def test_setup_streaming_session_persists_adhoc_metadata() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="do work")],
        project_id="agent-hub",
        adhoc=True,
        adhoc_spec=AdhocWorkSpec(
            title="Adhoc smoke",
            workload_profile="coding_impl",
        ),
    )
    session = type("Session", (), {"id": "sess-1", "provider_metadata": None})()
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
            resolved_agent=None,
            db=db,
            client_id="client-1",
            request_source="pytest",
        )

    assert session_id == "sess-1"
    assert is_new is True
    assert session.provider_metadata == {
        "adhoc": True,
        "adhoc_spec": {
            "title": "Adhoc smoke",
            "workload_profile": "coding_impl",
            "capabilities": {},
            "constraints": {},
        },
    }
