"""Generic event stream for async iteration with terminal-event resolution.

Direct port of pi-mono ``packages/ai/src/utils/event-stream.ts``. Providers
push events onto an :class:`EventStream`; consumers iterate via
``async for`` and may also ``await stream.result()`` for the terminal value.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from .types import (
    AssistantMessage,
    AssistantMessageEvent,
    DoneEvent,
    ErrorEvent,
)


class EventStream[T, R]:
    """Async iterable with a terminal-event result.

    ``is_complete`` and ``extract_result`` follow pi-mono's design:
    pushing an event for which ``is_complete`` returns true resolves
    ``result()`` to ``extract_result(event)``. Subsequent pushes are
    dropped. ``end()`` may close the stream early; if a result is supplied,
    it replaces any prior resolution.
    """

    def __init__(
        self,
        is_complete: Callable[[T], bool],
        extract_result: Callable[[T], R],
    ) -> None:
        self._is_complete = is_complete
        self._extract_result = extract_result
        self._queue: list[T] = []
        self._waiting: list[asyncio.Future[T | None]] = []
        self._done = False
        # Lazily created on first access from a running loop.
        self._result_future: asyncio.Future[R] | None = None
        self._pending_result: R | None = None
        self._has_pending_result = False

    def _ensure_future(self) -> asyncio.Future[R]:
        if self._result_future is None:
            self._result_future = asyncio.get_event_loop().create_future()
            if self._has_pending_result:
                # _pending_result is set together with _has_pending_result.
                self._result_future.set_result(self._pending_result)
        return self._result_future

    def _resolve(self, result: R) -> None:
        if self._has_pending_result:
            return
        self._has_pending_result = True
        self._pending_result = result
        if self._result_future is not None and not self._result_future.done():
            self._result_future.set_result(result)

    def push(self, event: T) -> None:
        if self._done:
            return

        if self._is_complete(event):
            self._done = True
            self._resolve(self._extract_result(event))

        if self._waiting:
            waiter = self._waiting.pop(0)
            if not waiter.done():
                waiter.set_result(event)
        else:
            self._queue.append(event)

    def end(self, result: R | None = None) -> None:
        self._done = True
        if result is not None:
            self._resolve(result)
        while self._waiting:
            waiter = self._waiting.pop(0)
            if not waiter.done():
                waiter.set_result(None)

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[T]:
        while True:
            if self._queue:
                yield self._queue.pop(0)
                continue
            if self._done:
                return
            loop = asyncio.get_event_loop()
            waiter: asyncio.Future[T | None] = loop.create_future()
            self._waiting.append(waiter)
            value = await waiter
            if value is None:
                return
            yield value

    async def result(self) -> R:
        return await self._ensure_future()


def _is_terminal(event: AssistantMessageEvent) -> bool:
    return event.type == "done" or event.type == "error"


def _extract_message(event: AssistantMessageEvent) -> AssistantMessage:
    if isinstance(event, DoneEvent):
        return event.message
    if isinstance(event, ErrorEvent):
        return event.error
    raise RuntimeError("Unexpected event type for final result")


class AssistantMessageEventStream(EventStream[AssistantMessageEvent, AssistantMessage]):
    """Specialization of :class:`EventStream` for assistant-message events."""

    def __init__(self) -> None:
        super().__init__(_is_terminal, _extract_message)


def create_assistant_message_event_stream() -> AssistantMessageEventStream:
    """Factory function (for use in extensions)."""

    return AssistantMessageEventStream()


__all__ = [
    "AssistantMessageEventStream",
    "EventStream",
    "create_assistant_message_event_stream",
]
