from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.adapters.base import ProviderError
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
async def test_stream_sdk_messages_allows_slow_post_tool_progress_without_synthesizing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> SlowIterator:
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
            if self._step == 1:
                self._step += 1
                await asyncio.sleep(0.01)
                return ResultMessage()
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return SlowIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]


@pytest.mark.asyncio
async def test_stream_sdk_messages_raises_provider_error_when_post_tool_progress_stalls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters import claude_tools_helpers as helpers

    class HangingIterator:
        def __init__(self) -> None:
            self._step = 0
            self._closed = False

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
            while not self._closed:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    continue
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self._closed = True

    def fake_query(*, prompt, options):
        return HangingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setattr(helpers, "_SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(ProviderError, match="stalled after tool_result"):
        async for _message, _session_id in _stream_sdk_messages("prompt", object(), "claude"):
            pass
