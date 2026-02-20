"""Tests for EventStream dual interface."""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.event_stream import EventStream


@pytest.mark.asyncio
async def test_push_and_iterate():
    """Events pushed to the stream are yielded in order."""
    stream: EventStream[str, str] = EventStream()
    await stream.push("a")
    await stream.push("b")
    await stream.end(result="done")

    events = [e async for e in stream]
    assert events == ["a", "b"]


@pytest.mark.asyncio
async def test_result_resolves_on_end():
    """Calling end() with a result resolves the .result() future."""
    stream: EventStream[str, str] = EventStream()
    await stream.push("event")
    await stream.end(result="final_value")

    result = await stream.result()
    assert result == "final_value"


@pytest.mark.asyncio
async def test_result_rejects_on_error():
    """Calling end() with an error rejects the .result() future."""
    stream: EventStream[str, str] = EventStream()
    await stream.end(error=ValueError("boom"))

    with pytest.raises(ValueError, match="boom"):
        await stream.result()


@pytest.mark.asyncio
async def test_push_after_end_raises():
    """Pushing to an ended stream raises RuntimeError."""
    stream: EventStream[str, str] = EventStream()
    await stream.end(result="done")

    with pytest.raises(RuntimeError, match="Cannot push"):
        await stream.push("late")


@pytest.mark.asyncio
async def test_ended_property():
    """The ended property reflects stream state."""
    stream: EventStream[str, str] = EventStream()
    assert stream.ended is False
    await stream.end(result="done")
    assert stream.ended is True


@pytest.mark.asyncio
async def test_concurrent_iteration_and_result():
    """Iteration and .result() can be used simultaneously."""
    stream: EventStream[int, str] = EventStream()

    collected: list[int] = []

    async def consumer() -> None:
        async for event in stream:
            collected.append(event)

    async def producer() -> None:
        for i in range(5):
            await stream.push(i)
            await asyncio.sleep(0)
        await stream.end(result="all_done")

    await asyncio.gather(consumer(), producer())

    assert collected == [0, 1, 2, 3, 4]
    assert await stream.result() == "all_done"


@pytest.mark.asyncio
async def test_from_async_iterator():
    """from_async_iterator wraps an existing async iterator."""

    async def gen():
        yield "a"
        yield "b"
        yield "done"

    stream = EventStream.from_async_iterator(
        gen(),
        result_extractor=lambda e: "finished" if e == "done" else None,
    )

    events = [e async for e in stream]
    assert events == ["a", "b", "done"]

    result = await stream.result()
    assert result == "finished"


@pytest.mark.asyncio
async def test_from_async_iterator_error():
    """from_async_iterator handles errors from the source iterator."""

    async def failing_gen():
        yield "a"
        raise ValueError("source error")

    stream = EventStream.from_async_iterator(failing_gen())

    events = [e async for e in stream]
    assert events == ["a"]

    with pytest.raises(ValueError, match="source error"):
        await stream.result()


@pytest.mark.asyncio
async def test_double_end_is_idempotent():
    """Calling end() twice does not raise."""
    stream: EventStream[str, str] = EventStream()
    await stream.end(result="first")
    await stream.end(result="second")  # Should not raise

    assert await stream.result() == "first"
