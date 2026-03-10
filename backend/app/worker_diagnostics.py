"""Worker diagnostics for inspecting live asyncio task state."""

from __future__ import annotations

import asyncio
import io
import logging
import signal
from collections.abc import Iterable
from concurrent.futures import Future

logger = logging.getLogger(__name__)


def _render_task_dump(tasks: Iterable[asyncio.Task[object]]) -> list[str]:
    """Render task metadata and stack snippets for log output."""
    lines: list[str] = []
    for task in tasks:
        coro = task.get_coro()
        coro_name = getattr(coro, "__qualname__", repr(coro))
        lines.append(
            f"task name={task.get_name()} done={task.done()} "
            f"cancelled={task.cancelled()} coro={coro_name}"
        )
        stream = io.StringIO()
        task.print_stack(limit=12, file=stream)
        dump = stream.getvalue().strip()
        if not dump:
            lines.append("  no Python stack available")
            continue
        for line in dump.splitlines():
            lines.append(f"  {line}")
    return lines


async def dump_asyncio_tasks() -> None:
    """Log all live asyncio tasks for the worker loop."""
    loop = asyncio.get_running_loop()
    current = asyncio.current_task(loop=loop)
    tasks = sorted(
        (task for task in asyncio.all_tasks(loop) if task is not current),
        key=lambda task: (task.done(), task.get_name()),
    )
    logger.warning("Worker asyncio task dump start: total=%d", len(tasks))
    for line in _render_task_dump(tasks):
        logger.warning("%s", line)
    logger.warning("Worker asyncio task dump end")


def install_asyncio_task_dump_signal(loop: asyncio.AbstractEventLoop | None) -> None:
    """Install SIGUSR1 handler that logs asyncio task state for the worker loop."""
    if loop is None or not hasattr(signal, "SIGUSR1"):
        return

    def _handle_sigusr1(_signum: int, _frame: object) -> None:
        future: Future[None] = asyncio.run_coroutine_threadsafe(dump_asyncio_tasks(), loop)

        def _log_done(done: Future[None]) -> None:
            exc = done.exception()
            if exc is not None:
                logger.exception("Worker asyncio task dump failed", exc_info=exc)

        future.add_done_callback(_log_done)

    signal.signal(signal.SIGUSR1, _handle_sigusr1)
    logger.info("Installed SIGUSR1 asyncio task dump handler for worker")
