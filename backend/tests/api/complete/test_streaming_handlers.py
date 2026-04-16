from __future__ import annotations

from unittest.mock import patch

from fastapi.responses import StreamingResponse

from app.api.complete.request_schemas import CompletionRequest, MessageInput
from app.api.complete.streaming_handlers import _build_sse_response


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
            db=None,
            is_new_session=True,
            tools=loaded_tools,
        )

    assert isinstance(response, StreamingResponse)
    assert mock_stream_completion.call_args.kwargs["max_tool_turns"] == 37
