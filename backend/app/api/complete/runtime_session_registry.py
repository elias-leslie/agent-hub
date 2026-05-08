"""Registry for active provider runtime sessions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class ActiveRuntimeSession:
    runtime_session: Any
    task: asyncio.Task[object] | None


class RuntimeSessionRegistry:
    """Track active non-streaming tool runtimes so close/cancel can stop work."""

    _active: ClassVar[dict[str, ActiveRuntimeSession]] = {}

    @classmethod
    def register(cls, session_id: str, runtime_session: Any) -> None:
        task = asyncio.current_task()
        cls._active[session_id] = ActiveRuntimeSession(runtime_session=runtime_session, task=task)

    @classmethod
    def unregister(cls, session_id: str, runtime_session: Any) -> None:
        active = cls._active.get(session_id)
        if active is not None and active.runtime_session is runtime_session:
            cls._active.pop(session_id, None)

    @classmethod
    async def cancel(cls, session_id: str) -> bool:
        active = cls._active.get(session_id)
        if active is None:
            return False
        with suppress(Exception):
            await active.runtime_session.interrupt()
        task = active.task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        return True
