"""Integration tests for the new pipeline orchestrator (Phase 3.1).

Verifies the orchestrator skeleton drives the new ``backend/app/llm/``
stack end-to-end via the faux provider — proves the wiring is correct
before the HTTP route flip in Phase 3.6.
"""

from __future__ import annotations

import pytest

from app.api.complete.orchestrator import (
    build_context_from_messages,
    run_completion,
    run_completion_stream,
)
from app.api.complete.sse_writer import SseWriter, write_events
from app.llm.providers.faux import (
    faux_assistant_message,
    faux_tool_call,
    register_faux_provider,
)
from app.llm.types import (
    AudioContent,
    Context,
    SimpleStreamOptions,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def test_build_context_from_messages_decodes_string_and_blocks() -> None:
    ctx = build_context_from_messages(
        [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "ABC",
                        },
                    },
                    {
                        "type": "audio",
                        "source": {
                            "type": "base64",
                            "media_type": "audio/wav",
                            "data": "UklGRg==",
                        },
                    },
                ],
            },
        ]
    )

    assert ctx.system_prompt == "you are helpful"
    assert len(ctx.messages) == 2
    first, second = ctx.messages
    assert isinstance(first, UserMessage)
    assert first.content == "hello"
    assert isinstance(second, UserMessage)
    assert isinstance(second.content, list)
    text_blocks = [b for b in second.content if isinstance(b, TextContent)]
    assert text_blocks and text_blocks[0].text == "look"
    audio_blocks = [b for b in second.content if isinstance(b, AudioContent)]
    assert audio_blocks == [AudioContent(data="UklGRg==", mime_type="audio/wav")]


@pytest.mark.asyncio
async def test_run_completion_non_streaming() -> None:
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("done")])
        model = reg.get_model()
        assert model is not None
        result = await run_completion(
            model,
            Context(messages=[UserMessage(content="hi", timestamp=0)]),
            options=SimpleStreamOptions(),
        )
        assert result.message.stop_reason == "stop"
        assert result.turns == 1
        assert result.tool_calls_count == 0
        text = "".join(b.text for b in result.message.content if isinstance(b, TextContent))
        assert "done" in text
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_run_completion_drives_tool_loop_and_writes_sse() -> None:
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [faux_tool_call("echo", {"text": "hi"}, id="t1")],
                    stop_reason="toolUse",
                ),
                faux_assistant_message("ack"),
            ]
        )
        model = reg.get_model()
        assert model is not None

        async def run_tool(call: ToolCall) -> ToolResultMessage:
            return ToolResultMessage(
                tool_call_id=call.id,
                tool_name=call.name,
                content=[TextContent(text="ok")],
                is_error=False,
                timestamp=0,
            )

        context = Context(messages=[UserMessage(content="run echo", timestamp=0)])
        result = await run_completion(
            model,
            context,
            execute_tools=True,
            run_tool=run_tool,
            options=SimpleStreamOptions(),
        )
        assert result.tool_calls_count == 1
        assert result.message.stop_reason == "stop"
        assert result.turns >= 2  # at least the two assistant turns
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_run_completion_stream_yields_events_for_sse_writer() -> None:
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("streamed")])
        model = reg.get_model()
        assert model is not None
        context = Context(messages=[UserMessage(content="hi", timestamp=0)])

        writer = SseWriter(session_id="sess-x")
        chunks: list[str] = []
        async for chunk in write_events(
            run_completion_stream(model, context, options=SimpleStreamOptions()),
            writer,
        ):
            chunks.append(chunk)

        assert chunks, "expected at least one SSE chunk"
        assert any("content" in c for c in chunks)
        assert any("done" in c for c in chunks)
    finally:
        reg.unregister()
