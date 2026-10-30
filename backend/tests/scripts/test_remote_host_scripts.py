"""Agent host scripts (scripts/remote-host/host): idle poweroff decision and the st guard."""

from __future__ import annotations

import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import pytest

HOST_DIR = Path(__file__).resolve().parents[3] / "scripts/remote-host/host"


def _idle() -> Any:
    return SourceFileLoader("agent_host_idle", str(HOST_DIR / "agent-host-idle")).load_module()


def _config(idle: Any, **overrides: Any) -> Any:
    values = {"enabled": True, "idle_minutes": 15.0, "load_max": 0.3, "load_window": 5, "tether_socket": "/x"}
    return idle.Config(**{**values, **overrides})


def test_shipped_config_holds_the_thresholds() -> None:
    idle = _idle()
    config = idle.load_config(HOST_DIR / "idle.conf")
    assert (config.enabled, config.idle_minutes, config.load_max, config.load_window) == (True, 15.0, 0.3, 5)


def test_idle_host_powers_off_only_after_the_idle_minutes() -> None:
    idle = _idle()
    config = _config(idle)
    quiet = idle.Reading(sessions=0, wakes=0, load=0.05, ssh=0, errors=())
    assert idle.decide(quiet, config, None, now=1000.0)[0] == "idle"
    assert idle.decide(quiet, config, 1000.0 - 14 * 60, now=1000.0)[0] == "idle"
    action, message = idle.decide(quiet, config, 1000.0 - 15 * 60, now=1000.0)
    assert action == "poweroff" and message.startswith("power off: idle 15 min")


@pytest.mark.parametrize(
    ("reading", "reason"),
    [
        ({"sessions": 1}, "1 Tether session(s)"),
        ({"wakes": 2}, "2 pending wake(s)"),
        ({"load": 0.3}, "load 0.30 >= 0.3"),
        ({"ssh": 1}, "1 ssh session(s) besides the link"),
        ({"sessions": None, "wakes": None, "errors": ("Tether unreadable (x)",)}, "Tether unreadable"),
    ],
)
def test_any_activity_or_unknown_keeps_the_host_up(reading: dict[str, Any], reason: str) -> None:
    idle = _idle()
    values = {"sessions": 0, "wakes": 0, "load": 0.0, "ssh": 0, "errors": (), **reading}
    action, message = idle.decide(idle.Reading(**values), _config(idle), 0.0, now=10_000.0)
    assert action == "busy" and reason in message


def test_disabled_config_never_powers_off() -> None:
    idle = _idle()
    quiet = idle.Reading(sessions=0, wakes=0, load=0.0, ssh=0, errors=())
    assert idle.decide(quiet, _config(idle, enabled=False), 0.0, now=10_000.0)[0] == "busy"


def _proc(root: Path, pid: int, ppid: int, cmdline: str) -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "stat").write_text(f"{pid} (x y) S {ppid} 0 0\n", encoding="utf-8")
    (entry / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode() + b"\0")


def test_ssh_sessions_ignores_the_link_and_counts_shells(tmp_path: Path) -> None:
    _proc(tmp_path, 10, 1, "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups")
    _proc(tmp_path, 20, 10, "sshd-session: kasadis [priv]")
    _proc(tmp_path, 21, 20, "sshd: kasadis")  # the Tether link: ssh -N, no children
    _proc(tmp_path, 30, 10, "sshd: kasadis [priv]")
    _proc(tmp_path, 31, 30, "sshd: kasadis@pts/0")
    _proc(tmp_path, 32, 31, "-bash")
    assert _idle().ssh_sessions(tmp_path) == 1


def _guard(tmp_path: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    guard = tmp_path / "st"
    guard.write_text((HOST_DIR / "st").read_text(encoding="utf-8").replace(
        "launcher=/srv/workspaces/projects/summitflow/scripts/st", f"launcher={tmp_path / 'launcher'}"
    ), encoding="utf-8")
    (tmp_path / "st-workstation-only").write_text((HOST_DIR / "st-workstation-only").read_text(encoding="utf-8"))
    launcher = tmp_path / "launcher"
    launcher.write_text('#!/bin/sh\necho "ran: $* db=${DATABASE_URL%%@*}"\n', encoding="utf-8")
    for path in (guard, launcher):
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    return subprocess.run([str(guard), *argv], env=env, capture_output=True, text=True, timeout=10, check=False)


def test_st_guard_refuses_workstation_only_commands_at_once(tmp_path: Path) -> None:
    refused = _guard(tmp_path, "vm", "list")
    assert refused.returncode == 2 and "st vm: workstation-only" in refused.stderr and not refused.stdout

    sub = _guard(tmp_path, "aico", "create", "x")
    assert sub.returncode == 2 and "st aico: workstation-only" in sub.stderr


def test_st_guard_runs_remote_commands_with_a_placeholder_database(tmp_path: Path) -> None:
    for argv in (("pulse", "--brief"), ("aico", "wake", "list"), ("--help",)):
        result = _guard(tmp_path, *argv)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"ran: {' '.join(argv)} db=postgresql://st-remote-host\n"
