"""Smoke tests for the faux provider.

Verifies the faux provider drives the full universal-stream pipeline so
future provider/tool-loop tests can use it as a drop-in instead of
hand-rolled monkey-patches.
"""

from __future__ import annotations

import pytest

from app.llm.api_registry import get_api_provider
from app.llm.providers.faux import (
    RegisterFauxProviderOptions,
    faux_assistant_message,
    faux_text,
    faux_thinking,
    faux_tool_call,
    register_faux_provider,
)
from app.llm.types import (
    AssistantMessage,
    Context,
    UserMessage,
)


@pytest.mark.asyncio
async def test_faux_provider_streams_text() -> None:
    reg = register_faux_provider(RegisterFauxProviderOptions(tokens_per_second=None))
    try:
        reg.set_responses([faux_assistant_message("hello world")])

        provider = get_api_provider(reg.api)
        assert provider is not None
        model = reg.get_model()
        assert model is not None

        stream = provider.stream(
            model,
            Context(messages=[UserMessage(content="hi", timestamp=0)]),
        )
        events = [e async for e in stream]
        final = await stream.result()

        assert isinstance(final, AssistantMessage)
        assert final.stop_reason == "stop"
        from app.llm.types import TextContent
        text = "".join(b.text for b in final.content if isinstance(b, TextContent))
        assert "hello world" in text
        assert events[0].type == "start"
        assert events[-1].type == "done"
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_faux_provider_streams_thinking_and_tool_call() -> None:
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [
                        faux_thinking("planning"),
                        faux_text("calling"),
                        faux_tool_call("echo", {"text": "x"}, id="t1"),
                    ],
                    stop_reason="toolUse",
                ),
            ]
        )

        provider = get_api_provider(reg.api)
        assert provider is not None
        model = reg.get_model()
        assert model is not None

        stream = provider.stream(
            model,
            Context(messages=[UserMessage(content="run echo", timestamp=0)]),
        )
        events = [e async for e in stream]
        final = await stream.result()
        types = [e.type for e in events]
        assert "thinking_start" in types
        assert "text_start" in types
        assert "toolcall_start" in types
        assert "toolcall_end" in types
        assert types[-1] == "done"
        assert final.stop_reason == "toolUse"
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_faux_provider_queues_errors_when_empty() -> None:
    reg = register_faux_provider()
    try:
        # No responses queued — provider should surface a queued-error
        provider = get_api_provider(reg.api)
        assert provider is not None
        model = reg.get_model()
        assert model is not None

        stream = provider.stream(
            model,
            Context(messages=[UserMessage(content="hi", timestamp=0)]),
        )
        final = await stream.result()
        assert final.stop_reason == "error"
        assert final.error_message and "No more faux responses" in final.error_message
    finally:
        reg.unregister()
