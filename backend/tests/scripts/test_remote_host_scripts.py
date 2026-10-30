"""Agent host scripts (scripts/remote-host): idle poweroff, clean snapshot, the st guard and bootstrap."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/remote-host"
HOST_DIR = SCRIPTS / "host"


def _idle() -> Any:
    return SourceFileLoader("agent_host_idle", str(HOST_DIR / "agent-host-idle")).load_module()


def _config(idle: Any, **overrides: Any) -> Any:
    values = {"enabled": True, "idle_minutes": 15.0, "load_max": 0.3, "load_window": 5, "tether_socket": "/x"}
    return idle.Config(**{**values, **overrides})


def test_shipped_config_holds_the_thresholds() -> None:
    idle = _idle()
    config = idle.load_config(HOST_DIR / "idle.conf")
    assert (config.enabled, config.idle_minutes, config.load_max, config.load_window) == (True, 15.0, 0.3, 5)
    assert "tether@*.service" in config.ignore_units and "tmux-spawn-*.scope" not in config.ignore_units
    assert {"sshd", "sshd-session"} <= set(config.ignore_commands)
    assert config.ignore_system_units == ("docker-*.scope",)


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
        ({"sessions": 1}, "1 Aico session(s) open"),
        ({"wakes": 2}, "2 scheduled check-in(s)"),
        ({"load": 0.3}, "load 0.30 >= 0.3"),
        ({"ssh": 1}, "1 ssh login(s) besides Aico's link"),
        ({"sessions": None, "wakes": None, "errors": ("Tether unreadable (x)",)}, "Tether unreadable"),
        ({"work": ("sleep", "make")}, "2 program(s) still running outside Aico sessions (make, sleep)"),
        ({"containers": 2}, "2 running container(s)"),
        ({"jobs": ("run-u12.service",)}, "1 background job(s) run as root (run-u12.service)"),
    ],
)
def test_any_activity_or_unknown_keeps_the_host_up(reading: dict[str, Any], reason: str) -> None:
    idle = _idle()
    values = {"sessions": 0, "wakes": 0, "load": 0.0, "ssh": 0, "errors": (), **reading}
    action, message = idle.decide(idle.Reading(**values), _config(idle), 0.0, now=10_000.0)
    assert action == "busy" and reason in message


def test_containers_count_running_ones_and_none_without_docker() -> None:
    idle = _idle()
    assert idle.containers(lambda argv, **_: subprocess.CompletedProcess(argv, 0, "a1\nb2\n", "")) == 2

    def missing(argv: list[str], **_: Any) -> Any:
        raise FileNotFoundError(argv[0])

    assert idle.containers(missing) == 0
    with pytest.raises(RuntimeError):
        idle.containers(lambda argv, **_: subprocess.CompletedProcess(argv, 1, "", "denied"))


def test_system_jobs_counts_root_systemd_run_units_only() -> None:
    idle = _idle()
    listed = "ssh.service loaded active running OpenSSH\nrun-u12.service loaded active running /bin/make\n"
    shown = "\n\n".join([
        "Id=ssh.service\nTransient=no\nSlice=system.slice",
        "Id=run-u12.service\nTransient=yes\nSlice=system.slice",
        "Id=docker-abc.scope\nTransient=yes\nSlice=system.slice",
        "Id=session-3.scope\nTransient=yes\nSlice=user-1000.slice",
    ])

    def run(argv: list[str], **_: Any) -> Any:
        return subprocess.CompletedProcess(argv, 0, listed if argv[1] == "list-units" else shown, "")

    config = _config(idle, ignore_system_units=("docker-*.scope",))
    assert idle.system_jobs(config, run) == ["run-u12.service"]
    with pytest.raises(RuntimeError):
        idle.system_jobs(config, lambda argv, **_: subprocess.CompletedProcess(argv, 1, "", ""))


def test_disabled_config_never_powers_off() -> None:
    idle = _idle()
    quiet = idle.Reading(sessions=0, wakes=0, load=0.0, ssh=0, errors=())
    assert idle.decide(quiet, _config(idle, enabled=False), 0.0, now=10_000.0)[0] == "busy"


def _proc(root: Path, pid: int, ppid: int, cmdline: str, cgroup: str = "/system.slice/ssh.service",
          comm: str | None = None, state: str = "S") -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "stat").write_text(f"{pid} (x y) {state} {ppid} 0 0\n", encoding="utf-8")
    (entry / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode() + b"\0")
    (entry / "cgroup").write_text(f"0::{cgroup}\n", encoding="utf-8")
    (entry / "comm").write_text((comm or cmdline.split()[0].split(":")[0]) + "\n", encoding="utf-8")


@pytest.mark.parametrize("title", ["sshd", "sshd-session"])  # OpenSSH before and from 9.8
def test_ssh_sessions_ignores_the_link_and_counts_shells(tmp_path: Path, title: str) -> None:
    _proc(tmp_path, 10, 1, "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups")
    _proc(tmp_path, 20, 10, f"{title}: kasadis [priv]")
    _proc(tmp_path, 21, 20, f"{title}: kasadis")  # the Tether link: ssh -N, no children
    _proc(tmp_path, 30, 10, f"{title}: kasadis [priv]")
    _proc(tmp_path, 31, 30, f"{title}: kasadis@notty")
    _proc(tmp_path, 32, 31, "-bash")
    assert _idle().ssh_sessions(tmp_path) == 1


def test_user_work_counts_detached_jobs_but_not_tether_or_user_daemons(tmp_path: Path) -> None:
    idle = _idle()
    config = idle.load_config(HOST_DIR / "idle.conf")
    user = "/user.slice/user-1000.slice"
    manager = f"{user}/user@1000.service"
    _proc(tmp_path, 1, 0, "/sbin/init", "/init.scope", "systemd")
    _proc(tmp_path, 861, 1, "/usr/lib/systemd/systemd --user", f"{manager}/init.scope", "systemd")
    _proc(tmp_path, 878, 861, "(sd-pam)", f"{manager}/init.scope", "(sd-pam)")
    _proc(tmp_path, 900, 861, "/usr/bin/dbus-daemon --session", f"{manager}/session.slice/dbus.service")
    _proc(tmp_path, 901, 861, "node tether", f"{manager}/app.slice/tether@default.service", "node")
    _proc(tmp_path, 902, 861, "tmux -S x", f"{manager}/app.slice/aico-tmux-server-b05e.service", "tmux: server")
    _proc(tmp_path, 950, 10, "sshd: kasadis [priv]", f"{user}/session-450.scope", "sshd")  # the link
    _proc(tmp_path, 951, 950, "sshd: kasadis@notty", f"{user}/session-450.scope", "sshd")
    assert idle.user_work(config, tmp_path) == []

    _proc(tmp_path, 960, 1, "sleep 301", f"{user}/session-451.scope")  # setsid -f, its ssh gone
    _proc(tmp_path, 970, 861, "make", f"{manager}/app.slice/run-u12.service")  # systemd-run --user
    _proc(tmp_path, 980, 1, "python3 job.py", f"{manager}/app.slice/tmux-spawn-972d.scope", "python3")
    _proc(tmp_path, 990, 1, "defunct", f"{user}/session-452.scope", state="Z")
    _proc(tmp_path, 991, 1, "bash -c check", f"{user}/session-499.scope", "bash")  # the caller's own session
    assert idle.user_work(config, tmp_path, exclude_cgroup=f"{user}/session-499.scope") == ["make", "python3", "sleep"]


def test_a_garbage_tether_answer_keeps_the_host_up_instead_of_crashing(tmp_path: Path) -> None:
    idle = _idle()
    path = str(tmp_path / "s.sock")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(4)

    def serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"garbage\r\n\r\n")

    threading.Thread(target=serve, daemon=True).start()
    try:
        reading = idle.read_host(_config(idle, tether_socket=path))
    finally:
        server.close()
    assert reading.sessions is None and reading.errors[0].startswith("Tether unreadable")
    assert idle.decide(reading, _config(idle), 0.0, now=10_000.0)[0] == "busy"


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


@pytest.mark.parametrize(
    "argv",
    [
        ("-P", "agent-hub", "service", "rebuild", "x"),
        ("--project", "x", "vm", "start", "200"),
        ("--project=x", "db", "query"),
        ("-Px", "vm", "list"),
        ("--human", "snap", "create"),
        ("-c", "service", "status"),
        ("--no-compact", "--progress-only", "--", "vm", "list"),
        ("-P", "x", "aico", "create"),
    ],
)
def test_st_guard_sees_the_command_after_global_options(tmp_path: Path, argv: tuple[str, ...]) -> None:
    result = _guard(tmp_path, *argv)
    assert result.returncode == 2 and "workstation-only" in result.stderr and not result.stdout


def test_st_guard_refuses_an_unknown_option_before_the_command(tmp_path: Path) -> None:
    result = _guard(tmp_path, "-cP", "x", "vm", "start")
    assert result.returncode == 2 and "unknown global option -cP" in result.stderr and not result.stdout


def test_st_guard_runs_remote_commands_with_a_placeholder_database(tmp_path: Path) -> None:
    for argv in (("pulse", "--brief"), ("aico", "wake", "list"), ("--help",), ("-P", "agent-hub", "pulse"),
                 ("--project=x", "-c", "aico", "wake", "list")):
        result = _guard(tmp_path, *argv)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"ran: {' '.join(argv)} db=postgresql://st-remote-host\n"


def test_clean_snapshot_removes_read_only_trees_without_following_links(tmp_path: Path) -> None:
    prepare = SourceFileLoader("prepare_clean_snapshot", str(HOST_DIR / "prepare-clean-snapshot")).load_module()
    tree, outside = tmp_path / "context-deliveries", tmp_path / "outside"
    (tree / "claude_code/agent-hub").mkdir(parents=True)
    (tree / "claude_code/agent-hub/CLAUDE.md").write_text("context", encoding="utf-8")
    outside.mkdir()
    (outside / "keep").write_text("x", encoding="utf-8")
    (tree / "claude_code/link").symlink_to(outside)
    for directory in (tree / "claude_code/agent-hub", tree / "claude_code", outside):
        directory.chmod(0o555)
    try:
        prepare._remove_tree(tree)
        assert not tree.exists()
        assert (outside / "keep").exists() and outside.stat().st_mode & 0o777 == 0o555
    finally:
        outside.chmod(0o755)


def test_clean_snapshot_wipes_read_only_scratch_trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepare = SourceFileLoader("prepare_clean_snapshot", str(HOST_DIR / "prepare-clean-snapshot")).load_module()
    scratch = tmp_path / "scratch"
    (scratch / "gomod/pkg").mkdir(parents=True)
    (scratch / "gomod/pkg/mod.go").write_text("x", encoding="utf-8")
    (scratch / "loose").write_text("x", encoding="utf-8")
    for directory in (scratch / "gomod/pkg", scratch / "gomod"):
        directory.chmod(0o555)
    systemctl: list[list[str]] = []
    monkeypatch.setattr(prepare, "SCRATCH", scratch)
    monkeypatch.setattr(prepare, "STATE_DIR", tmp_path / "none")
    monkeypatch.setattr(prepare, "CONTEXT_ARTIFACTS", tmp_path / "none")
    monkeypatch.setattr(prepare, "refusals", lambda config: [])
    monkeypatch.setattr(prepare, "_wait_healthy", lambda config: {"catalog": {"sessions": 0}})
    monkeypatch.setattr(prepare.subprocess, "run", lambda argv, **_: systemctl.append(argv))
    assert prepare.main(["--config", str(HOST_DIR / "idle.conf")]) == 0
    assert list(scratch.iterdir()) == []
    assert [argv[2] for argv in systemctl] == ["stop", "start"]


def test_clean_snapshot_refuses_while_user_work_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    prepare = SourceFileLoader("prepare_clean_snapshot", str(HOST_DIR / "prepare-clean-snapshot")).load_module()
    idle = prepare.idle
    monkeypatch.setattr(idle, "tether_get", lambda _sock, path: {"catalog": {}} if path == "/v1/health" else {"items": [], "roots": []})
    monkeypatch.setattr(prepare.subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 1, "", ""))
    monkeypatch.setattr(idle, "ssh_sessions", lambda: 1)
    monkeypatch.setattr(idle, "user_work", lambda config, exclude_cgroup=None: ["sleep"])
    found = prepare.refusals(idle.load_config(HOST_DIR / "idle.conf"))
    assert "1 program(s) still running outside Aico sessions (sleep)" in found
    assert {"docker unreadable", "system units unreadable"} <= set(found)


def test_clean_snapshot_counts_only_roots_that_have_not_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ended root keeps its record (and the catalog's rootRequests count) until the state is cleared."""
    prepare = SourceFileLoader("prepare_clean_snapshot", str(HOST_DIR / "prepare-clean-snapshot")).load_module()
    idle = prepare.idle
    answers = {
        "/v1/health": {"catalog": {"sessions": 0, "tmuxServersActive": 0, "rootRequests": 3}},
        "/v1/wakes": {"items": []},
        "/v1/roots": {"roots": [{"status": "ended"}, {"status": "ended"}, {"status": "running"}]},
    }
    monkeypatch.setattr(idle, "tether_get", lambda _sock, path: answers[path])
    monkeypatch.setattr(prepare.subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 1, "", ""))
    monkeypatch.setattr(idle, "ssh_sessions", lambda: 1)
    monkeypatch.setattr(idle, "user_work", lambda config, exclude_cgroup=None: [])
    config = idle.load_config(HOST_DIR / "idle.conf")
    assert "1 agent launch(es) not ended yet" in prepare.refusals(config)
    answers["/v1/roots"]["roots"].pop()
    assert not any("agent launch" in reason for reason in prepare.refusals(config))


def test_bootstrap_on_host_never_eats_a_loop_input(tmp_path: Path) -> None:
    """Every hook file in the list is copied, not just the first (ssh reads stdin unless -n)."""
    helpers = [line for line in (SCRIPTS / "bootstrap").read_text(encoding="utf-8").splitlines()
               if line.startswith(("ssh_opts=", "on_host()", "on_host_stdin()"))]
    assert len(helpers) == 3
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "ssh").write_text('#!/bin/sh\nfor a; do last=$a; done\ncase " $* " in *" -n "*) ;; *) cat >/dev/null ;; esac\n')
    (stub / "ssh").chmod(0o755)
    script = "\n".join([
        "set -euo pipefail", "host=h", *helpers,
        "links=$(printf 'link\\ta\\tb\\nfile\\tone.sh\\nfile\\ttwo.sh\\nfile\\tthree.sh\\n')",
        "while IFS=$'\\t' read -r kind path _; do",
        "  [[ $kind == file ]] || continue",
        '  on_host mkdir -p x && echo "$path"',
        'done <<<"$links"',
    ])
    result = subprocess.run(["bash", "-c", script], env={**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"},
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["one.sh", "two.sh", "three.sh"]


def test_home_links_map_a_deployed_release_to_the_mirrored_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host has no deployed releases: a link into one (Pi's st-coord.ts) points at the checkout's copy."""
    links = SourceFileLoader("home_links", str(HOST_DIR.parent / "home-links")).load_module()
    releases, projects = tmp_path / "releases", tmp_path / "projects"
    source = releases / "summitflow/releases/abc/source/scripts/lib/pi-coord-extension.ts"
    source.parent.mkdir(parents=True)
    source.write_text("x")
    checkout = projects / "summitflow/scripts/lib/pi-coord-extension.ts"
    checkout.parent.mkdir(parents=True)
    checkout.write_text("x")
    monkeypatch.setattr(links, "RELEASES", releases)
    monkeypatch.setattr(links, "PROJECTS", projects)
    assert links.release_source(source, {"summitflow"}) == checkout
    assert links.release_source(source, {"agent-hub"}) is None
    assert links.release_source(tmp_path / "elsewhere.ts", {"summitflow"}) is None
