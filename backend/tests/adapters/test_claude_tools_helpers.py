from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.adapters.claude_tools_helpers import _stream_sdk_messages


class ResultMessage:
    pass


@pytest.mark.asyncio
async def test_stream_sdk_messages_drains_after_result_message(monkeypatch: pytest.MonkeyPatch) -> None:
    yielded = []

    async def fake_query(*, prompt, options):
        yielded.append("assistant")
        yield types.SimpleNamespace(content=[], subtype=None)
        yielded.append("result")
        yield ResultMessage()
        yielded.append("after-result")
        yield types.SimpleNamespace(content=[], subtype=None)

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]
    assert yielded == ["assistant", "result", "after-result"]


@pytest.mark.asyncio
async def test_stream_sdk_messages_synthesizes_result_when_stream_ends_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_query(*, prompt, options):
        yield types.SimpleNamespace(content=[], subtype=None)

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]


@pytest.mark.asyncio
async def test_stream_sdk_messages_synthesizes_result_after_idle_post_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters import claude_tools_helpers as helpers

    class HangingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> HangingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                block = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="ok",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[block], subtype=None)
            await asyncio.Event().wait()
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return HangingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setattr(helpers, "_SDK_TERMINAL_GRACE_SECONDS", 0.01)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]
