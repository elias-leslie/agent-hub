"""Processes a workflow attempt starts: who they are, how to stop them, and how to find them again after a crash.

Every harness (and acceptance command) runs in its own session and process group. The attempt records each one's
pid, process group and start time (``/proc/<pid>/stat``); a later sweep may only signal a recorded group after it has
confirmed the pid still belongs to that start time, so a recycled pid is never signalled. A group whose leader is
already gone is only touched when its members carry the attempt's marker in their environment (the kernel keeps a
process-group id from being reused while any member lives). Tools a harness starts often leave its group (a shell
tool of its own session); they inherit the marker too, so after the group is stopped every process still carrying the
attempt's marker is stopped as well. Nothing here matches processes by name.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)

# Set in every process an attempt starts; how a leaderless group is proven to be the attempt's.
MARKER_ENV = "AGENT_HUB_WORKFLOW_ATTEMPT"
POLL_SECONDS = 0.05
PROC = Path("/proc")


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    pgid: int
    start_time: int  # clock ticks since boot, /proc/<pid>/stat field 22
    boot_id: str

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "pgid": self.pgid, "start_time": self.start_time, "boot_id": self.boot_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProcessIdentity | None:
        try:
            return cls(int(value["pid"]), int(value["pgid"]), int(value["start_time"]), str(value["boot_id"]))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class _Stat:
    state: str
    pgrp: int
    session: int
    start_time: int


def read_stat(pid: int) -> _Stat | None:
    """State, process group, session and start time of ``pid``; None when it does not exist."""

    try:
        text = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    # The command name is in parentheses and may itself contain spaces and parentheses: split after the last one.
    fields = text[text.rindex(")") + 2 :].split()
    try:
        return _Stat(fields[0], int(fields[2]), int(fields[3]), int(fields[19]))
    except (IndexError, ValueError):
        return None


def boot_id() -> str:
    try:
        return (PROC / "sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def identify(pid: int) -> ProcessIdentity | None:
    """The identity of a process started with ``start_new_session`` (its group is its own pid)."""

    stat = read_stat(pid)
    if stat is None:
        return None
    return ProcessIdentity(pid, stat.pgrp, stat.start_time, boot_id())


def _live_members(pgid: int) -> list[int]:
    """Pids of the non-zombie processes in process group ``pgid``."""

    members: list[int] = []
    for entry in os.listdir(PROC):
        if entry.isdigit() and (stat := read_stat(int(entry))) and stat.pgrp == pgid and stat.state != "Z":
            members.append(int(entry))
    return members


def _carries_marker(pid: int, marker: str) -> bool:
    try:
        environ = (PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return False
    return f"{MARKER_ENV}={marker}".encode() in environ.split(b"\0")


def inspect_group(identity: ProcessIdentity, marker: str | None) -> str:
    """``live`` when the recorded group is still there and provably ours, else why not.

    ``gone``: nothing of it runs. ``pid_reused``: the pid now belongs to another process (other start time).
    ``other_boot``: recorded before the last reboot. ``unverified``: members exist but cannot be tied to the attempt.
    ``refused``: the recorded group is not one this process may signal (its own group, or a system id).
    """

    if identity.pgid <= 1 or identity.pgid == os.getpgrp():
        return "refused"
    if identity.boot_id != boot_id():
        return "other_boot"
    leader = read_stat(identity.pid)
    if leader is not None and leader.start_time != identity.start_time:
        return "pid_reused"
    if leader is not None and leader.state != "Z":
        return "live"
    members = _live_members(identity.pgid)
    if not members:
        return "gone"
    if leader is not None:  # a zombie leader with our start time: the group's members are its own
        return "live"
    # Leader gone, group still occupied: the id cannot be reused while a member lives, but only the attempt's own
    # processes carry its marker.
    if marker and any(_carries_marker(pid, marker) for pid in members):
        return "live"
    return "unverified"


def _signal_group(pgid: int, sig: signal.Signals) -> bool:
    """Send ``sig`` to the group; False when no such group exists."""

    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    return True


def _group_exists(pgid: int) -> bool:
    """Whether any process of the group still runs (a zombie waiting to be reaped does not count)."""

    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return bool(_live_members(pgid))


async def wait_exit(process: asyncio.subprocess.Process, timeout: float | None) -> bool:
    """Whether the child itself exited within ``timeout`` seconds (``None``: wait for the exit however long it takes).

    ``Process.wait()`` also waits for the child's pipes to close, so a grandchild that inherited stdout would hold it
    for as long as it lives; the child's own exit is read from its return code instead.
    """

    deadline = None if timeout is None else time.monotonic() + timeout
    while process.returncode is None:
        if deadline is not None and time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_SECONDS)
    return True


async def _wait_gone(pgid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while await asyncio.to_thread(_group_exists, pgid):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_SECONDS)
    return True


def _marked(marker: str) -> list[tuple[int, int, int]]:
    """``(pid, pgid, start_time)`` of the live processes carrying ``marker`` in their environment, except this one."""

    found: list[tuple[int, int, int]] = []
    for entry in os.listdir(PROC):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        stat = read_stat(int(entry))
        if stat is not None and stat.state != "Z" and _carries_marker(int(entry), marker):
            found.append((int(entry), stat.pgrp, stat.start_time))
    return found


def _signal_marked(found: list[tuple[int, int, int]], sig: signal.Signals) -> None:
    for pid, _pgid, start_time in found:
        stat = read_stat(pid)
        if stat is None or stat.start_time != start_time:  # gone, or the pid now belongs to another process
            continue
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)


async def stop_marked(marker: str, grace: float) -> list[dict[str, Any]]:
    """Stop what the attempt's process groups did not cover: processes that carry its marker but left the group.

    SIGTERM, then SIGKILL after ``grace`` seconds (``grace`` 0 kills at once). Each result is
    ``{pid, pgid, recovery}`` with ``recovery`` ``terminated``, ``killed`` or ``survived``.
    """

    found = await asyncio.to_thread(_marked, marker)
    if not found:
        return []
    deadline = time.monotonic() + grace
    outcome = "terminated"
    if grace > 0:
        await asyncio.to_thread(_signal_marked, found, signal.SIGTERM)
        while await asyncio.to_thread(_marked, marker) and time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
    left = await asyncio.to_thread(_marked, marker)
    if left:
        outcome = "killed"
        await asyncio.to_thread(_signal_marked, left, signal.SIGKILL)
        deadline = time.monotonic() + max(grace, 1.0)
        while await asyncio.to_thread(_marked, marker) and time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
    survivors = {pid for pid, _, _ in await asyncio.to_thread(_marked, marker)}
    return [
        {"pid": pid, "pgid": pgid, "recovery": "survived" if pid in survivors else outcome}
        for pid, pgid, _ in found
    ]


async def stop_group(identity: ProcessIdentity, marker: str | None, grace: float) -> str:
    """SIGTERM the recorded group, SIGKILL it after ``grace`` seconds; returns what happened.

    ``terminated`` (the group left within the grace period), ``killed`` (it needed SIGKILL), ``survived`` (still
    there after SIGKILL), or the reason it was left alone (see ``inspect_group``).
    """

    verdict = await asyncio.to_thread(inspect_group, identity, marker)
    if verdict != "live":
        return verdict
    if not _signal_group(identity.pgid, signal.SIGTERM):
        return "gone"
    if await _wait_gone(identity.pgid, grace):
        return "terminated"
    _signal_group(identity.pgid, signal.SIGKILL)
    return "killed" if await _wait_gone(identity.pgid, max(grace, 1.0)) else "survived"


async def kill_group(identity: ProcessIdentity, marker: str | None) -> str:
    """SIGKILL the recorded group at once (a command that overran its time, or left children behind)."""

    verdict = await asyncio.to_thread(inspect_group, identity, marker)
    if verdict != "live":
        return verdict
    _signal_group(identity.pgid, signal.SIGKILL)
    return "killed" if await _wait_gone(identity.pgid, 5.0) else "survived"


@dataclass
class TrackedProcess:
    """A child the attempt started, with the identity recorded at spawn."""

    process: asyncio.subprocess.Process
    identity: ProcessIdentity | None
    marker: str | None
    kind: str

    async def stop(self, grace: float) -> str:
        """End the whole group (the child and everything it started) and reap the child."""

        verdict = await self._act(lambda i: stop_group(i, self.marker, grace))
        await self._sweep(grace)
        await self.reap()
        return verdict

    async def kill(self) -> str:
        verdict = await self._act(lambda i: kill_group(i, self.marker))
        await self._sweep(0)
        await self.reap()
        return verdict

    async def _sweep(self, grace: float) -> None:
        # Children of the process that left its group; they carry the same marker.
        if self.marker:
            await stop_marked(self.marker, grace)

    async def _act(self, action: Callable[[ProcessIdentity], Awaitable[str]]) -> str:
        if self.identity is None:
            return "unknown"
        return await action(self.identity)

    async def reap(self) -> None:
        # The leader is dead once its group was killed; the bound only guards a process stuck in the kernel.
        await wait_exit(self.process, 10)


Recorder = Callable[[dict[str, Any]], Awaitable[None]]


class ProcessTracker:
    """Every process one attempt starts, so none can outlive it: recorded on the attempt, stopped at the end."""

    def __init__(self, marker: str, record: Recorder | None = None) -> None:
        self.marker = marker
        self._record = record
        self.processes: list[TrackedProcess] = []

    async def add(self, tracked: TrackedProcess) -> None:
        self.processes.append(tracked)
        if tracked.identity is None or self._record is None:
            return
        try:
            await self._record({"kind": tracked.kind, **tracked.identity.as_dict(), "started_at": time.time()})
        except Exception:
            logger.warning("could not record %s process %s", tracked.kind, tracked.identity.pid, exc_info=True)

    async def release(self, tracked: TrackedProcess) -> None:
        """Forget a finished process whose group is empty; one still holding members stays for the final stop."""

        if tracked.identity is None or tracked.process.returncode is None:
            return
        if await asyncio.to_thread(_live_members, tracked.identity.pgid):
            return
        if tracked in self.processes:
            self.processes.remove(tracked)

    def harness(self) -> TrackedProcess | None:
        """The attempt's harness process (the latest one started), if it has started one."""

        return next((p for p in reversed(self.processes) if p.kind == "harness"), None)

    async def stop_all(self, grace: float) -> list[str]:
        """Stop every process still around; errors in one do not stop the others."""

        results = await asyncio.gather(*(p.stop(grace) for p in self.processes), return_exceptions=True)
        return [r if isinstance(r, str) else f"error: {r!r}" for r in results]


current_tracker: ContextVar[ProcessTracker | None] = ContextVar("workflow_process_tracker", default=None)


async def start_tracked(
    *command: str,
    kind: str,
    working_dir: Path | None = None,
    env: dict[str, str] | None = None,
    stdin: int | None = None,
    stdout: int | None = asyncio.subprocess.PIPE,
    stderr: int | None = asyncio.subprocess.PIPE,
    limit: int | None = None,
) -> TrackedProcess:
    """Start a child in its own session that dies with this process, and register it with the attempt's tracker."""

    tracker = current_tracker.get()
    # Outside an attempt the child still gets a marker of its own, so a group it leaves behind can be proven its.
    marker = tracker.marker if tracker is not None else uuid.uuid4().hex
    env = {**(os.environ if env is None else env), MARKER_ENV: marker}
    process = await create_process(
        *command,
        working_dir=working_dir,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
        limit=limit,
        die_with_parent=True,
    )
    tracked = TrackedProcess(process, await asyncio.to_thread(identify, process.pid), marker, kind)
    if tracker is not None:
        await tracker.add(tracked)
    return tracked
