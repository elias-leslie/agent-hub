"""The host-side shim and agent-hub command, run as real processes against a fake Agent Hub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "integrations/remote-host/agent-hub-host"
TOKEN = "ahh_" + "h" * 43
SECRET = "dummy-secret-value"

ROWS = [
    {"tool_slug": "dummy", "name": "key", "command": "dummy-tool", "config_dir": "~/.dummy",
     "env_var": "DUMMY_KEY", "auth_file": None, "rotates": False, "stored": True, "expired": False,
     "expires_at": None, "undecodable": False},
    {"tool_slug": "filed", "name": "creds", "command": "filed-tool", "config_dir": "~/.filed",
     "env_var": None, "auth_file": "auth/creds.json", "rotates": False, "stored": True, "expired": False,
     "expires_at": None, "undecodable": False},
    {"tool_slug": "codex", "name": "login", "command": "codex", "config_dir": "~/.codex",
     "env_var": None, "auth_file": "auth.json", "rotates": True, "stored": False, "expired": False,
     "expires_at": None, "undecodable": False},
]


class FakeHub:
    def __init__(self) -> None:
        self.granted = ["dummy", "filed"]
        self.requests: list[tuple[str, str, str | None, Any]] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return None

            def _answer(self, code: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                hub.requests.append((method, self.path, self.headers.get("Authorization"), body))
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._answer(401, {"detail": "no"})
                if method == "GET" and self.path == "/api/host-credentials/tools":
                    return self._answer(200, {"host": "agent-work", "granted_tools": hub.granted, "credentials": ROWS})
                tool = self.path.rsplit("/", 2)[-1] if method == "GET" else self.path.split("/")[-2]
                if tool not in hub.granted:
                    return self._answer(403, {"detail": "no"})
                if method == "PUT":
                    return self._answer(200, {"stored": True, "expires_at": (body or {}).get("expires_at")})
                rows = [row for row in ROWS if row["tool_slug"] == tool]
                return self._answer(200, {"tool": tool, "credentials": [
                    {key: row[key] for key in ("name", "config_dir", "env_var", "auth_file")} | {"value": SECRET}
                    for row in rows
                ]})

            def do_GET(self) -> None:
                self._route("GET")

            def do_PUT(self) -> None:
                self._route("PUT")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def hub() -> Generator[FakeHub]:
    fake = FakeHub()
    yield fake
    fake.server.shutdown()


@pytest.fixture
def host(tmp_path: Path, hub: FakeHub) -> dict[str, Any]:
    """A fake host home: next binaries that report what they received, and a private runtime dir."""
    home = tmp_path / "home"
    runtime = tmp_path / "run"
    native = tmp_path / "native"
    report = tmp_path / "report.json"
    for path in (home, runtime, native):
        path.mkdir(mode=0o700)
    for command in ("dummy-tool", "filed-tool", "codex"):
        tool = native / command
        tool.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            "auth = os.path.expanduser('~/.filed/auth/creds.json')\n"
            f"json.dump({{'argv': sys.argv, 'key': os.environ.get('DUMMY_KEY'), "
            f"'file': open(auth).read() if os.path.exists(auth) else None}}, open({str(report)!r}, 'w'))\n"
        )
        tool.chmod(0o755)
    env = {
        "HOME": str(home), "XDG_RUNTIME_DIR": str(runtime), "AGENT_HUB_URL": hub.url,
        "PATH": f"{home}/.local/lib/agent-hub/cred-bin:{native}:/usr/bin:/bin",
    }
    return {"home": home, "runtime": runtime, "report": report, "env": env}


def _run(host: dict[str, Any], *argv: str, stdin: str | None = None, env: dict[str, str] | None = None,
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), input=stdin, capture_output=True, text=True, timeout=20,
                          env={**host["env"], **(env or {})}, check=False)


def _install(host: dict[str, Any]) -> None:
    # argv[0] picks the mode, so run through the "agent-hub" name as the host does.
    link = host["home"] / ".local/bin/agent-hub"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(SCRIPT)
    result = _run(host, str(link), "install", "--token-stdin", stdin=TOKEN + "\n")
    assert result.returncode == 0, result.stderr


def test_install_saves_a_private_token_and_shims_only_served_granted_tools(host: dict[str, Any]) -> None:
    _install(host)
    home = host["home"]
    token = home / ".config/agent-hub/host-token"
    assert token.read_text().strip() == TOKEN and token.stat().st_mode & 0o777 == 0o600
    shims = sorted(path.name for path in (home / ".local/lib/agent-hub/cred-bin").iterdir())
    assert shims == ["dummy-tool", "filed-tool"]  # codex rotates: signed in on the host, no shim
    assert json.loads((home / ".config/agent-hub/cred-shims.json").read_text()) == {
        "dummy-tool": "dummy", "filed-tool": "filed",
    }


def test_shim_sets_the_env_var_and_execs_the_next_binary(host: dict[str, Any]) -> None:
    _install(host)
    result = _run(host, "dummy-tool", "--resume", "abc")
    assert result.returncode == 0, result.stderr
    report = json.loads(host["report"].read_text())
    assert report["key"] == SECRET
    assert report["argv"][1:] == ["--resume", "abc"]
    assert SECRET not in result.stdout + result.stderr


def test_shim_links_a_private_runtime_file_into_the_real_config_dir(host: dict[str, Any]) -> None:
    _install(host)
    assert _run(host, "filed-tool").returncode == 0
    assert json.loads(host["report"].read_text())["file"] == SECRET
    target = host["home"] / ".filed/auth/creds.json"
    source = Path(os.readlink(target))
    assert source.is_relative_to(host["runtime"])
    assert source.stat().st_mode & 0o777 == 0o600
    assert (host["home"] / ".filed").is_dir() and not (host["home"] / ".filed").is_symlink()
    assert _run(host, "filed-tool").returncode == 0  # relaunch reuses the link


def test_shim_never_overwrites_a_host_local_login(host: dict[str, Any]) -> None:
    _install(host)
    local = host["home"] / ".filed/auth/creds.json"
    local.parent.mkdir(parents=True)
    local.write_text('{"mine": true}')
    result = _run(host, "filed-tool")
    assert result.returncode == 1 and "holds a login on this host" in result.stderr
    assert local.read_text() == '{"mine": true}' and not host["report"].exists()


@pytest.mark.parametrize("case", ["no-token", "unreachable", "revoked", "not-granted", "no-xdg"])
def test_shim_fails_closed_with_one_line_and_never_runs_the_tool(
    host: dict[str, Any], hub: FakeHub, case: str,
) -> None:
    _install(host)
    env: dict[str, str] = {}
    command = "dummy-tool"
    if case == "no-token":
        (host["home"] / ".config/agent-hub/host-token").unlink()
    elif case == "unreachable":
        env["AGENT_HUB_URL"] = "http://127.0.0.1:9"
    elif case == "revoked":
        (host["home"] / ".config/agent-hub/host-token").write_text("ahh_revoked\n")
    elif case == "not-granted":
        hub.granted = ["filed"]
    else:
        env["XDG_RUNTIME_DIR"] = ""
        command = "filed-tool"
    result = _run(host, command, env=env)
    assert result.returncode == 1
    assert len(result.stderr.strip().splitlines()) == 1
    assert result.stderr.startswith("agent-hub-cred-exec: ")
    assert not host["report"].exists()


def test_version_and_help_pass_straight_through_without_a_fetch(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    (host["home"] / ".config/agent-hub/host-token").unlink()
    before = len(hub.requests)
    for flag in ("--version", "--help"):
        assert _run(host, "dummy-tool", flag).returncode == 0
        assert json.loads(host["report"].read_text())["key"] is None
    assert len(hub.requests) == before


def test_cred_exec_form_and_native_bypass(host: dict[str, Any]) -> None:
    _install(host)
    bin_dir = host["home"] / ".local/bin"
    assert _run(host, str(bin_dir / "agent-hub-cred-exec"), "dummy", "x").returncode == 0
    assert json.loads(host["report"].read_text())["key"] == SECRET
    assert _run(host, str(bin_dir / "agent-hub"), "native", "dummy-tool", "setup-token").returncode == 0
    report = json.loads(host["report"].read_text())
    assert report["key"] is None and report["argv"][1:] == ["setup-token"]


def test_push_reads_stdin_and_sends_no_argv_secret(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    result = _run(host, str(host["home"] / ".local/bin/agent-hub"), "credential", "push", "dummy",
                  stdin=SECRET + "\n")
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout
    method, path, _, body = hub.requests[-1]
    assert (method, path, body) == ("PUT", "/api/host-credentials/dummy/key", {"value": SECRET, "expires_at": None})


def test_login_status_reports_served_and_host_logins(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    agent_hub = str(host["home"] / ".local/bin/agent-hub")
    hub.granted = ["dummy"]
    report = json.loads(_run(host, agent_hub, "login", "status", "--json").stdout)
    states = {tool["tool"]: (tool["state"], tool["source"]) for tool in report["tools"]}
    assert states == {
        "dummy": ("signed_in", "agent-hub"),
        "filed": ("needs_sign_in", "agent-hub"),
        "codex": ("needs_sign_in", f"host:{host['home']}/.codex/auth.json"),
    }
    codex = host["home"] / ".codex/auth.json"
    codex.parent.mkdir()
    codex.write_text('{"tokens": {}}')
    offline = json.loads(_run(host, agent_hub, "login", "status", "--json",
                              env={"AGENT_HUB_URL": "http://127.0.0.1:9"}).stdout)
    states = {tool["tool"]: tool["state"] for tool in offline["tools"]}
    assert states == {"dummy": "unknown", "filed": "unknown", "codex": "signed_in"}
    assert "unreachable" in offline["agent_hub"]
