"""Persistent Claude Code CLI processes, one per Agent Hub conversation.

A fresh ``claude -p`` process per request rewrites the whole history into the
prompt cache every turn. A long-lived process fed one user message per turn
writes only the delta. The pool keeps such processes keyed by
``(session_id, model, effort, system-prompt hash)``; the provider decides per
request whether the transcript the process has already seen is a prefix of the
new request (``ClaudeSession.seen``), and replaces the process when it is not.

Turns are serialized per process with ``ClaudeSession.lock``. Idle expiry and
the pool cap come from settings; app shutdown calls ``close_all``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.safe_subprocess import create_process

from .claude_code_cli import child_env

PoolKey = tuple[str, str, str | None, str]

_STREAM_LIMIT = 64 * 1024 * 1024
_STDERR_TAIL = 2_000


def pool_key(session_id: str, model_id: str, effort: str | None, system_prompt: str | None) -> PoolKey:
    return (session_id, model_id, effort, hashlib.sha256((system_prompt or "").encode()).hexdigest())


@dataclass(eq=False)
class ClaudeSession:
    key: PoolKey | None
    process: asyncio.subprocess.Process
    workdir: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Stable hashes of the messages (user turns sent, assistant replies produced) this process holds.
    seen: list[str] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)
    _stderr: bytearray = field(default_factory=bytearray)
    _stderr_task: asyncio.Task[None] | None = None
    _idle: asyncio.TimerHandle | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    @property
    def stderr_tail(self) -> str:
        return bytes(self._stderr).decode("utf-8", errors="replace")

    async def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        while chunk := await self.process.stderr.read(4096):
            self._stderr += chunk
            del self._stderr[:-_STDERR_TAIL]

    @classmethod
    async def start(
        cls,
        key: PoolKey | None,
        system_prompt: str | None,
        make_argv: Callable[[Path | None], list[str]],
    ) -> ClaudeSession:
        """Launch a locked session in a private empty working directory."""
        workdir = Path(tempfile.mkdtemp(prefix="agent-hub-claude-"))
        try:
            prompt_file = None
            if system_prompt:
                prompt_file = workdir / "system-prompt.md"
                prompt_file.write_text(system_prompt, encoding="utf-8")
            run_dir = workdir / "run"
            run_dir.mkdir(mode=0o700)
            process = await create_process(
                *make_argv(prompt_file),
                working_dir=run_dir,
                env=child_env(),
                stdin=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
            )
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        session = cls(key=key, process=process, workdir=workdir)
        session._stderr_task = asyncio.create_task(session._drain_stderr())
        await session.lock.acquire()
        return session

    async def close(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        if self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
        await self.process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
        shutil.rmtree(self.workdir, ignore_errors=True)


class ClaudePool:
    def __init__(self) -> None:
        self._sessions: dict[PoolKey, ClaudeSession] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def checkout(self, key: PoolKey) -> ClaudeSession | None:
        """Return the live pooled session for ``key`` with its turn lock held."""
        while (session := self._sessions.get(key)) is not None:
            await session.lock.acquire()
            if self._sessions.get(key) is session and session.alive:
                if session._idle is not None:
                    session._idle.cancel()
                    session._idle = None
                return session
            session.lock.release()
            if self._sessions.get(key) is session:
                await self.discard(session)
        return None

    async def add(self, session: ClaudeSession) -> None:
        """Pool a freshly started session, evicting stale siblings and the oldest idle ones past the cap."""
        if session.key is None:
            return
        from app.config import settings

        for other in [s for s in self._sessions.values() if s.key is not None and s.key[0] == session.key[0] and not s.lock.locked()]:
            await self.discard(other)
        while len(self._sessions) >= settings.claude_session_pool_max:
            idle = [s for s in self._sessions.values() if not s.lock.locked()]
            if not idle:
                break
            await self.discard(min(idle, key=lambda s: s.last_used))
        self._sessions[session.key] = session

    def release(self, session: ClaudeSession, seen: list[str]) -> None:
        """Hand back a healthy session after a clean turn."""
        from app.config import settings

        session.seen = seen
        session.last_used = time.monotonic()
        session._idle = asyncio.get_running_loop().call_later(
            settings.claude_session_idle_seconds, self._expire, session
        )
        session.lock.release()

    async def discard(self, session: ClaudeSession) -> None:
        """Kill and forget a session; waiters on its lock find it gone."""
        if session.key is not None and self._sessions.get(session.key) is session:
            del self._sessions[session.key]
        await session.close()
        if session.lock.locked():
            with contextlib.suppress(RuntimeError):
                session.lock.release()

    def _expire(self, session: ClaudeSession) -> None:
        if session.lock.locked():
            return
        task = asyncio.create_task(self.discard(session))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close_all(self) -> None:
        for session in list(self._sessions.values()):
            await self.discard(session)


claude_pool = ClaudePool()


async def shutdown_claude_sessions() -> None:
    await claude_pool.close_all()
