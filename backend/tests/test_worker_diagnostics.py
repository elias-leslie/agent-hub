from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from app.worker_diagnostics import _render_task_dump


@pytest.mark.asyncio
async def test_render_task_dump_includes_task_name_and_stack() -> None:
    gate = asyncio.Event()

    async def _waiter() -> None:
        await gate.wait()

    task = asyncio.create_task(_waiter(), name="diagnostic-waiter")
    try:
        await asyncio.sleep(0)
        dump = _render_task_dump([task])
        assert any("diagnostic-waiter" in line for line in dump)
        assert any("_waiter" in line for line in dump)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
