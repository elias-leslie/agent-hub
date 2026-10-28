"""Process identity, group stop, parent-death and acceptance clean-up, against small real process trees."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.workflow_runs import acceptance
from app.services.workflow_runs.processes import (
    MARKER_ENV,
    ProcessIdentity,
    ProcessTracker,
    current_tracker,
    identify,
    inspect_group,
    read_stat,
    start_tracked,
    stop_group,
    stop_marked,
)

# A leader and a grandchild; the grandchild's pid is printed. With IGNORE the grandchild ignores SIGTERM.
TREE = (
    "import json, os, signal, subprocess, sys, time\n"
    "code = 'import signal, time\\n' + ('signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n' if sys.argv[1:] else '') + "
    "'time.sleep(300)'\n"
    "child = subprocess.Popen([sys.executable, '-c', code])\n"
    "print(json.dumps({'child': child.pid}), flush=True)\n"
    "time.sleep(300)\n"
)


def alive(pid: int) -> bool:
    stat = read_stat(pid)
    return stat is not None and stat.state != "Z"


async def gone(*pids: int, within: float = 10.0) -> bool:
    deadline = time.monotonic() + within
    while any(alive(pid) for pid in pids):
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


def spawn_tree(*args: str, marker: str | None = None) -> tuple[subprocess.Popen[str], int]:
    env = {**os.environ, **({MARKER_ENV: marker} if marker else {})}
    proc = subprocess.Popen(
        [sys.executable, "-c", TREE, *args], start_new_session=True, stdout=subprocess.PIPE, text=True, env=env
    )
    assert proc.stdout is not None
    return proc, json.loads(proc.stdout.readline())["child"]


async def test_identity_reads_the_start_time_even_when_the_command_name_has_parentheses(tmp_path: Path) -> None:
    script = tmp_path / "a (b) c"
    script.write_text("#!/bin/sh\nexec sleep 30\n")
    script.chmod(0o755)
    proc = subprocess.Popen([str(script)], start_new_session=True)
    try:
        await asyncio.sleep(0.2)
        identity = identify(proc.pid)
        assert identity is not None and identity.pgid == proc.pid and identity.start_time > 0
        assert identify(proc.pid) == identity
    finally:
        proc.kill()
        proc.wait()


async def test_stop_group_ends_a_leader_and_a_grandchild_that_ignores_sigterm() -> None:
    proc, child = spawn_tree("ignore")
    await asyncio.sleep(0.5)  # the grandchild has installed its handler
    identity = identify(proc.pid)
    assert identity is not None
    started = time.monotonic()
    assert await stop_group(identity, None, 0.5) == "killed"  # the leader left on SIGTERM; the grandchild needed SIGKILL
    proc.wait(timeout=5)
    assert await gone(child, within=3) and time.monotonic() - started < 5
    assert await stop_group(identity, None, 0.5) == "gone"


async def test_a_reused_pid_is_never_signalled() -> None:
    bystander = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        real = identify(bystander.pid)
        assert real is not None
        stale = ProcessIdentity(real.pid, real.pgid, real.start_time - 5, real.boot_id)
        assert inspect_group(stale, "any") == "pid_reused"
        assert await stop_group(stale, "any", 0.2) == "pid_reused"
        other_boot = ProcessIdentity(real.pid, real.pgid, real.start_time, "not-this-boot")
        assert await stop_group(other_boot, "any", 0.2) == "other_boot"
        assert alive(bystander.pid)
        assert inspect_group(ProcessIdentity(1, 1, 1, real.boot_id), None) == "refused"
        assert inspect_group(ProcessIdentity(os.getpid(), os.getpgrp(), 1, real.boot_id), None) == "refused"
    finally:
        bystander.kill()
        bystander.wait()


async def test_a_group_whose_leader_died_is_stopped_only_when_its_members_carry_the_marker() -> None:
    marked, marked_child = spawn_tree(marker="attempt-1")
    unmarked, unmarked_child = spawn_tree()
    try:
        marked_id, unmarked_id = identify(marked.pid), identify(unmarked.pid)
        assert marked_id is not None and unmarked_id is not None
        for leader in (marked, unmarked):
            os.kill(leader.pid, signal.SIGKILL)  # the harness died with its worker; its tool process lives on
            leader.wait()
        assert inspect_group(marked_id, "attempt-1") == "live"
        assert inspect_group(marked_id, "another-attempt") == "unverified"
        assert inspect_group(unmarked_id, "attempt-1") == "unverified"
        assert await stop_group(marked_id, "attempt-1", 2) == "terminated"
        assert await gone(marked_child, within=3) and alive(unmarked_child)
    finally:
        for pid in (marked_child, unmarked_child):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


async def test_a_child_dies_with_its_parent_even_in_its_own_session(tmp_path: Path) -> None:
    script = tmp_path / "parent.py"
    script.write_text(
        "import asyncio, sys\n"
        "from app.utils.safe_subprocess import create_process\n"
        "async def main():\n"
        "    p = await create_process('sleep', '300', die_with_parent=True)\n"
        "    print(p.pid, flush=True)\n"
        "    await asyncio.sleep(300)\n"
        "asyncio.run(main())\n"
    )
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True, cwd=Path.cwd())
    assert parent.stdout is not None
    child = int(parent.stdout.readline())
    assert alive(child) and os.getpgid(child) == child  # its own session, so no group signal from the parent's reaches it
    parent.kill()
    parent.wait()
    assert await gone(child, within=5)


async def test_start_tracked_marks_records_and_stops_everything_the_attempt_started() -> None:
    recorded: list[dict] = []

    async def record(entry: dict) -> None:
        recorded.append(entry)

    tracker = ProcessTracker("attempt-9", record)
    token = current_tracker.set(tracker)
    try:
        tracked = await start_tracked(sys.executable, "-c", TREE, kind="harness", env={"PATH": os.environ["PATH"]})
    finally:
        current_tracker.reset(token)
    assert tracked.process.stdout is not None
    child = json.loads(await tracked.process.stdout.readline())["child"]
    assert [(r["kind"], r["pid"], r["pgid"]) for r in recorded] == [("harness", tracked.process.pid, tracked.process.pid)]
    assert f"{MARKER_ENV}=attempt-9".encode() in Path(f"/proc/{child}/environ").read_bytes().split(b"\0")
    assert await tracker.stop_all(2) == ["terminated"]
    assert await gone(tracked.process.pid, child, within=3) and tracked.process.returncode is not None


async def test_acceptance_timeout_kills_the_command_and_its_lingering_grandchild(tmp_path: Path) -> None:
    results = await acceptance.run_acceptance(
        [{"cmd": "sleep 300 & echo $! > gc.pid; wait", "timeout_s": 1}],
        tmp_path,
        tail_chars=500,
        drain_seconds=2,
    )
    (result,) = results
    assert (result["timed_out"], result["exit_code"], result["passed"]) == (True, None, False)
    assert result["duration_s"] < 8
    assert await gone(int((tmp_path / "gc.pid").read_text()), within=3)


async def test_acceptance_has_no_default_time_limit_and_a_commands_own_timeout_still_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect
    from types import SimpleNamespace

    from app.services.workflow_runs import processes

    assert "default_timeout" not in inspect.signature(acceptance.run_acceptance).parameters
    offset = 0.0
    monkeypatch.setattr(
        processes, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + offset, time=time.time)
    )

    async def two_hours_pass() -> None:
        nonlocal offset
        await asyncio.sleep(0.2)
        offset += 2 * 3600  # far past the 600 s the old default allowed

    passing = asyncio.create_task(two_hours_pass())
    results = await acceptance.run_acceptance(
        [{"cmd": "sleep 0.8; echo finished", "timeout_s": None}, {"cmd": "sleep 30", "timeout_s": 1}],
        tmp_path,
        tail_chars=500,
        drain_seconds=2,
    )
    await passing
    unlimited, limited = results
    assert (unlimited["timed_out"], unlimited["exit_code"], unlimited["passed"]) == (False, 0, True)
    assert unlimited["output_tail"] == "finished"
    assert (limited["timed_out"], limited["passed"]) == (True, False)


async def test_a_grandchild_holding_the_output_pipe_does_not_turn_a_finished_command_into_a_timeout(
    tmp_path: Path,
) -> None:
    (result,) = await acceptance.run_acceptance(
        [{"cmd": "sleep 300 & echo $! > gc.pid; echo checked", "timeout_s": 20}],
        tmp_path,
        tail_chars=500,
        drain_seconds=2,
    )
    assert (result["timed_out"], result["exit_code"], result["passed"]) == (False, 0, True)
    assert result["output_tail"] == "checked" and result["duration_s"] < 10
    assert await gone(int((tmp_path / "gc.pid").read_text()), within=3)


# A harness whose tool runs in a session of its own (what a shell tool does): it is outside the harness's group.
DETACHED = (
    "import json, subprocess, sys, time\n"
    "child = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
    "print(json.dumps({'child': child.pid}), flush=True)\n"
    "time.sleep(300)\n"
)


async def test_a_tool_that_left_the_harness_group_is_stopped_by_the_attempt_marker() -> None:
    tracker = ProcessTracker("attempt-detached")
    token = current_tracker.set(tracker)
    try:
        tracked = await start_tracked(sys.executable, "-c", DETACHED, kind="harness", env={"PATH": os.environ["PATH"]})
    finally:
        current_tracker.reset(token)
    assert tracked.process.stdout is not None
    tool = json.loads(await tracked.process.stdout.readline())["child"]
    stat = read_stat(tool)
    assert stat is not None and stat.pgrp != tracked.process.pid  # not covered by the harness's group
    assert await tracker.stop_all(2) == ["terminated"]
    assert await gone(tracked.process.pid, tool, within=5)


async def test_only_processes_carrying_the_marker_are_swept() -> None:
    ours = subprocess.Popen(
        ["sleep", "300"], start_new_session=True, env={**os.environ, MARKER_ENV: "attempt-sweep"}
    )
    other = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        await asyncio.sleep(0.2)
        result = await stop_marked("attempt-sweep", 0)
        assert [(r["pid"], r["recovery"]) for r in result] == [(ours.pid, "killed")]
        assert await gone(ours.pid, within=5)
        assert alive(other.pid)
        assert await stop_marked("attempt-sweep", 0) == []
    finally:
        for proc in (ours, other):
            proc.kill()
            proc.wait()
