from __future__ import annotations

import asyncio
import sys
import types

import pytest


class ResultMessage:
    def __init__(self, usage: dict[str, int] | None = None) -> None:
        self.usage = usage or {}


class AssistantMessage:
    def __init__(self, content: list[object]) -> None:
        self.content = content


@pytest.mark.asyncio
async def test_yield_sdk_events_closes_after_result_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator_holder: dict[str, object] = {}

    class ClosingIterator:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                return AssistantMessage([types.SimpleNamespace(type="text", text="hello")])
            if self._step == 1:
                self._step += 1
                return ResultMessage({"input_tokens": 1, "output_tokens": 2})
            raise AssertionError("stream should be closed immediately after ResultMessage")

        async def aclose(self) -> None:
            self.closed = True

    def fake_query(*, prompt, options):
        iterator = ClosingIterator()
        iterator_holder["iterator"] = iterator
        return iterator

    fake_types = types.SimpleNamespace(
        AssistantMessage=AssistantMessage,
        ResultMessage=ResultMessage,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(query=fake_query))
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types)

    from app.adapters.claude_streaming import _yield_sdk_events

    seen = []
    async for event in _yield_sdk_events("prompt", object()):
        seen.append((event.type, event.content, event.output_tokens))

    iterator = iterator_holder["iterator"]
    assert seen == [("content", "hello", None), ("done", "", 2)]
    assert iterator.closed is True


@pytest.mark.asyncio
async def test_yield_sdk_events_interrupts_owned_session_on_abort_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.base import StreamEvent
    from app.adapters.claude_streaming import _yield_sdk_events

    interrupt_log: list[str] = []

    class FakeIterator:
        def __init__(self, interrupted: asyncio.Event) -> None:
            self._step = 0
            self._interrupted = interrupted

        def __aiter__(self) -> FakeIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                return AssistantMessage([types.SimpleNamespace(type="text", text="hello")])
            await self._interrupted.wait()
            raise asyncio.CancelledError("interrupted")

        async def aclose(self) -> None:
            interrupt_log.append("close")

    class FakeSession:
        def __init__(self, prompt: object, options: object) -> None:
            del prompt, options
            self._interrupted = asyncio.Event()
            self.message_iter = FakeIterator(self._interrupted)

        async def start(self) -> None:
            interrupt_log.append("start")

        async def interrupt(self) -> None:
            interrupt_log.append("interrupt")
            self._interrupted.set()

        async def close(self) -> None:
            interrupt_log.append("session_close")

    fake_types = types.SimpleNamespace(
        AssistantMessage=AssistantMessage,
        ResultMessage=ResultMessage,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types)
    monkeypatch.setattr("app.adapters.claude_streaming._ClaudeSDKQuerySession", FakeSession)

    abort_event = asyncio.Event()
    seen: list[StreamEvent] = []

    with pytest.raises(asyncio.CancelledError):
        async for event in _yield_sdk_events("prompt", object(), abort_event=abort_event):
            seen.append(event)
            abort_event.set()

    assert [(event.type, event.content) for event in seen] == [("content", "hello")]
    assert interrupt_log == ["start", "interrupt", "session_close"]
