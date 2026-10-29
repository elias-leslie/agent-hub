"""Stop a provider request the moment its abort signal is set, not at its next chunk.

A provider's read loop only looks at ``options.signal`` when a chunk arrives; a model that is quiet (or a
connection that stalls) would keep the request, and its bill, open until then. ``cancel_on_signal`` ties the
request's task to the signal: setting the signal cancels the task, which closes the provider's HTTP stream.
Nothing here ends a request on elapsed time or silence; only the signal does.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from typing import Any


def cancel_on_signal(task: asyncio.Task[Any], signal: asyncio.Event | None) -> None:
    """Cancel ``task`` when ``signal`` is set; a no-op without a signal."""
    if signal is None:
        return

    async def watch() -> None:
        await signal.wait()
        task.cancel()

    watcher = asyncio.create_task(watch(), name="provider-abort-watch")
    task.add_done_callback(lambda _task: watcher.cancel())


async def close_quietly(handle: Any) -> None:
    """Close a provider's response stream (``close`` or ``aclose``), which releases its HTTP connection."""
    if handle is None:
        return
    for name in ("aclose", "close"):
        closer = getattr(handle, name, None)
        if closer is None:
            continue
        with contextlib.suppress(Exception):
            result = closer()
            if inspect.isawaitable(result):
                await result
        return
