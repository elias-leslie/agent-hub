"""Dual-interface event stream: async iteration + .result() awaitable.

Modeled after pi-mono's EventStream<T, R> pattern.  Consumers can either:

1. Iterate events as they arrive::

       async for event in stream:
           handle(event)

2. Await the final result (resolves on "done" or "error")::

       result = await stream.result()

Both interfaces can be used simultaneously.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class EventStream[T, R]:
    """Dual interface: async iteration + .result() awaitable.

    Producers push events with :meth:`push` and signal completion with
    :meth:`end`.  Consumers iterate events with ``async for`` and/or
    await the final result with :meth:`result`.

    Usage (producer side)::

        stream = EventStream()
        await stream.push(StreamEvent(type="content", content="hello"))
        await stream.push(StreamEvent(type="done", ...))
        await stream.end(CompletionResult(...))

    Usage (consumer side)::

        async for event in stream:
            if event.type == "content":
                print(event.content)
        final = await stream.result()
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[T | None] = asyncio.Queue()
        self._result_future: asyncio.Future[R] = asyncio.get_event_loop().create_future()
        self._ended = False

    async def push(self, event: T) -> None:
        """Push an event to the stream.

        Events are buffered in an internal queue and yielded to consumers
        via ``async for``.

        Raises:
            RuntimeError: If the stream has already ended.
        """
        if self._ended:
            raise RuntimeError("Cannot push to an ended stream")
        await self._queue.put(event)

    async def end(self, result: R | None = None, error: Exception | None = None) -> None:
        """Signal the end of the stream.

        Resolves the :meth:`result` future and sends a sentinel ``None``
        to stop iteration.

        Args:
            result: The final result to resolve the future with.
            error: An exception to reject the future with.

        Exactly one of ``result`` or ``error`` must be provided.
        """
        if self._ended:
            return
        self._ended = True

        # Signal end of iteration
        await self._queue.put(None)

        # Resolve the result future
        if not self._result_future.done():
            if error is not None:
                self._result_future.set_exception(error)
            elif result is not None:
                self._result_future.set_result(result)

    def result(self) -> asyncio.Future[R]:
        """Return a future that resolves when the stream ends.

        Can be awaited to get the final result::

            final = await stream.result()
        """
        return self._result_future

    @property
    def ended(self) -> bool:
        """True if :meth:`end` has been called."""
        return self._ended

    def __aiter__(self) -> AsyncIterator[T]:
        return self._async_iter()

    async def _async_iter(self) -> AsyncIterator[T]:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item

    @classmethod
    def from_async_iterator(
        cls,
        iterator: AsyncIterator[T],
        result_extractor: Any | None = None,
    ) -> EventStream[T, R]:
        """Create an EventStream that wraps an existing async iterator.

        Useful for adapting legacy ``stream()`` methods that return
        ``AsyncIterator[StreamEvent]`` into the dual-interface pattern.

        Args:
            iterator: The async iterator to wrap.
            result_extractor: Optional callable ``(T) -> R | None`` that
                extracts a result from a "done" event.  If it returns a
                value, that becomes the stream result.
        """
        stream: EventStream[T, R] = cls.__new__(cls)
        stream._queue = asyncio.Queue()
        stream._result_future = asyncio.get_event_loop().create_future()
        stream._ended = False

        async def _pump() -> None:
            last_result: R | None = None
            try:
                async for event in iterator:
                    await stream._queue.put(event)
                    if result_extractor is not None:
                        extracted = result_extractor(event)
                        if extracted is not None:
                            last_result = extracted
                await stream.end(result=last_result)
            except Exception as exc:
                await stream.end(error=exc)

        stream._pump_task = asyncio.ensure_future(_pump())
        return stream
