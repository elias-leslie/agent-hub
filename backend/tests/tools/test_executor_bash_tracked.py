"""Bash commands of a workflow attempt are recorded with the attempt's tracker; ordinary chat bash is not."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from app.services.tools import _executor_bash
from app.services.workflow_runs.processes import (
    MARKER_ENV,
    ProcessTracker,
    current_tracker,
    read_stat,
)


@pytest.fixture(autouse=True)
def allow_test_bash_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.tools._executor_bash.get_command_guard_block_reason",
        lambda *_args, **_kwargs: None,
    )


def alive(pid: int) -> bool:
    stat = read_stat(pid)
    return stat is not None and stat.state != "Z"


async def until(predicate, within: float = 10.0) -> bool:
    deadline = time.monotonic() + within
    while not predicate():
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


@pytest.mark.asyncio
async def test_attempt_bash_carries_the_marker_and_is_recorded(tmp_path: Path) -> None:
    recorded: list[dict] = []

    async def record(entry: dict) -> None:
        recorded.append(entry)

    tracker = ProcessTracker("attempt-bash", record)
    token = current_tracker.set(tracker)
    try:
        output = await _executor_bash.run_bash(f"echo ${MARKER_ENV}", tmp_path, dict(os.environ))
    finally:
        current_tracker.reset(token)
    assert output.strip() == "attempt-bash"
    assert [r["kind"] for r in recorded] == ["tool"]
    assert recorded[0]["pgid"] == recorded[0]["pid"]
    assert tracker.processes == []  # finished with an empty group: nothing left to stop


@pytest.mark.asyncio
async def test_attempt_bash_survivors_are_stopped_with_the_attempt(tmp_path: Path) -> None:
    """A backgrounded child outlives its command; a command that left its session is found by the marker."""

    tracker = ProcessTracker("attempt-left", None)
    token = current_tracker.set(tracker)
    try:
        output = await _executor_bash.run_bash(
            "sleep 300 >/dev/null 2>&1 & echo $!; setsid sleep 301 >/dev/null 2>&1 & sleep 0.2", tmp_path, dict(os.environ)
        )
    finally:
        current_tracker.reset(token)
    same_group = int(output.split()[0])
    assert alive(same_group)
    assert len(tracker.processes) == 1  # its group still has a member: kept for the final stop
    marked = [p for p in os.listdir("/proc") if p.isdigit() and _carries(int(p), "attempt-left") and int(p) != os.getpid()]
    assert marked
    await tracker.stop_all(1)
    assert await until(lambda: not alive(same_group))
    assert await until(lambda: not any(alive(int(p)) for p in marked))


def _carries(pid: int, marker: str) -> bool:
    try:
        return f"{MARKER_ENV}={marker}".encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False


@pytest.mark.asyncio
async def test_stopping_the_attempt_ends_a_running_command(tmp_path: Path) -> None:
    tracker = ProcessTracker("attempt-run", None)
    token = current_tracker.set(tracker)
    try:
        task = asyncio.create_task(_executor_bash.run_bash("sleep 300", tmp_path, dict(os.environ)))
    finally:
        current_tracker.reset(token)
    assert await until(lambda: len(tracker.processes) == 1)
    pid = tracker.processes[0].process.pid
    assert alive(pid)
    await tracker.stop_all(1)
    assert await until(lambda: not alive(pid))
    assert "exited with code" in await asyncio.wait_for(task, 10)


@pytest.mark.asyncio
async def test_chat_bash_is_not_tracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    async def no_tracking(*_args, **_kwargs):
        started.append("tracked")
        raise AssertionError("chat bash must not go through the attempt tracker")

    monkeypatch.setattr(_executor_bash, "start_tracked", no_tracking)
    env = {k: v for k, v in os.environ.items() if k != MARKER_ENV}
    assert (await _executor_bash.run_bash(f"echo ${{{MARKER_ENV}:-none}}", tmp_path, env)).strip() == "none"
    assert started == []
