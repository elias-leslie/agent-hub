from __future__ import annotations

import asyncio

import pytest

from app.api.complete.runtime_session_registry import RuntimeSessionRegistry


class FakeRuntimeSession:
    def __init__(self) -> None:
        self.interrupted = False

    async def interrupt(self) -> None:
        self.interrupted = True


@pytest.mark.asyncio
async def test_runtime_session_cancel_interrupts_and_cancels_task() -> None:
    runtime = FakeRuntimeSession()
    registered = asyncio.Event()

    async def run_registered() -> None:
        RuntimeSessionRegistry.register("sess-cancel", runtime)
        registered.set()
        try:
            await asyncio.Event().wait()
        finally:
            RuntimeSessionRegistry.unregister("sess-cancel", runtime)

    task = asyncio.create_task(run_registered())
    await registered.wait()

    assert await RuntimeSessionRegistry.cancel("sess-cancel") is True

    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.interrupted is True
    assert await RuntimeSessionRegistry.cancel("sess-cancel") is False
