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
        self.rows = list(ROWS)
        # Agent Hub's public launch rules answer: (status, body)
        self.launch: tuple[int, Any] = (200, {"rows": [{"allowed": True, "deny_reason": None}]})
        self.truncate = False  # promise more body than is sent, like a dropped forward
        self.requests: list[tuple[str, str, str | None, Any]] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return None

            def _answer(self, code: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data) + 50 * hub.truncate))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                hub.requests.append((method, self.path, self.headers.get("Authorization"), body))
                if method == "GET" and self.path.startswith("/api/models/launch-defaults?"):
                    return self._answer(*hub.launch)
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._answer(401, {"detail": "no"})
                if method == "GET" and self.path == "/api/host-credentials/tools":
                    return self._answer(200, {"host": "agent-work", "granted_tools": hub.granted, "credentials": hub.rows})
                tool = self.path.rsplit("/", 2)[-1] if method == "GET" else self.path.split("/")[-2]
                if tool not in hub.granted:
                    return self._answer(403, {"detail": "no"})
                if method == "PUT":
                    return self._answer(200, {"stored": True, "expires_at": (body or {}).get("expires_at")})
                rows = [row for row in hub.rows if row["tool_slug"] == tool]
                return self._answer(200, {"tool": tool, "credentials": [
                    {key: row[key] for key in ("name", "config_dir", "env_var", "auth_file")} | {"value": row.get("value", SECRET)}
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
    for command in ("dummy-tool", "filed-tool", "codex", "claude", "pi"):
        tool = native / command
        tool.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            "auth = os.path.expanduser('~/.filed/auth/creds.json')\n"
            f"json.dump({{'argv': sys.argv, 'key': os.environ.get('DUMMY_KEY'), "
            "'claude': os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'), "
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
    # The first install runs the checkout file by path; it links the "agent-hub" name itself.
    result = _run(host, str(SCRIPT), "install", "--token-stdin", stdin=TOKEN + "\n")
    assert result.returncode == 0, result.stderr
    assert (host["home"] / ".local/bin/agent-hub").resolve() == SCRIPT


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


def test_parallel_launches_of_a_file_tool_all_start(host: dict[str, Any]) -> None:
    _install(host)
    procs = [subprocess.Popen(["filed-tool"], env=host["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) for _ in range(30)]
    results = [(proc.wait(timeout=30), proc.stderr.read()) for proc in procs]  # type: ignore[union-attr]
    assert [rc for rc, _ in results] == [0] * 30, [err for rc, err in results if rc]
    source = Path(os.readlink(host["home"] / ".filed/auth/creds.json"))
    assert source.read_text() == SECRET
    assert sorted(path.name for path in source.parent.iterdir()) == [source.name]  # no staging files left


def test_placing_the_file_concurrently_never_fails_or_refuses(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.machinery import SourceFileLoader

    monkeypatch.setenv("HOME", str(host["home"]))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(host["runtime"]))
    module = SourceFileLoader("agent_hub_host_race", str(SCRIPT)).load_module()
    item = {"name": "main", "config_dir": str(host["home"] / ".cfg"), "auth_file": "tokens/fake", "value": SECRET}
    errors: list[str] = []

    def worker() -> None:
        for _ in range(200):
            try:
                module._place_file("faketool", item)
            except Exception as exc:  # every failure is the finding
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_a_file_that_cannot_be_placed_is_one_line_and_the_tool_never_runs(host: dict[str, Any]) -> None:
    _install(host)
    (host["home"] / ".filed").write_text("not a directory")
    result = _run(host, "filed-tool")
    assert result.returncode == 1 and len(result.stderr.strip().splitlines()) == 1
    assert result.stderr.startswith("agent-hub-cred-exec: filed: cannot place the credential file")
    assert not host["report"].exists()


def test_short_flags_pass_straight_through_without_a_fetch(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    before = len(hub.requests)
    for flag in ("-v", "-h"):
        assert _run(host, "dummy-tool", flag, env={"AGENT_HUB_URL": "http://127.0.0.1:9"}).returncode == 0
        assert json.loads(host["report"].read_text())["key"] is None
    assert len(hub.requests) == before


def test_a_rejected_install_keeps_the_working_token(host: dict[str, Any]) -> None:
    _install(host)
    token = host["home"] / ".config/agent-hub/host-token"
    result = _run(host, str(SCRIPT), "install", "--token-stdin", stdin="ahh_TYPO\n")
    assert result.returncode == 1 and "unknown or revoked" in result.stderr
    assert token.read_text().strip() == TOKEN
    assert _run(host, "dummy-tool").returncode == 0


def test_a_truncated_answer_is_one_line_and_never_a_traceback(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    hub.truncate = True
    result = _run(host, "dummy-tool")
    assert result.returncode == 1 and len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr and not host["report"].exists()


def test_the_host_token_never_goes_through_an_environment_proxy(host: dict[str, Any], hub: FakeHub) -> None:
    _install(host)
    proxy = "http://127.0.0.1:9"  # nothing listens: a proxied request would fail
    result = _run(host, "dummy-tool", env={"http_proxy": proxy, "HTTP_PROXY": proxy, "all_proxy": proxy})
    assert result.returncode == 0, result.stderr
    assert hub.requests[-1][2] == f"Bearer {TOKEN}"


# Claude credentials and the session's work role -------------------------------------------------

CLAUDE_ROW = {"tool_slug": "claude-code", "name": "oauth-token", "command": "claude", "config_dir": "~/.claude",
              "env_var": "CLAUDE_CODE_OAUTH_TOKEN", "auth_file": None, "rotates": False, "stored": True,
              "expired": False, "expires_at": None, "undecodable": False}
DENY = "Owner 2026-11-01: Claude never for active hunting or recon"


def _claude_host(host: dict[str, Any], hub: FakeHub) -> None:
    hub.rows.append(CLAUDE_ROW)
    hub.granted.append("claude-code")
    _install(host)


def _fetched(hub: FakeHub, tool: str) -> bool:
    return any(path == f"/api/host-credentials/{tool}" for _, path, _, _ in hub.requests)


def test_claude_credentials_are_refused_to_a_session_whose_work_role_is_denied(host: dict[str, Any], hub: FakeHub) -> None:
    _claude_host(host, hub)
    hub.launch = (200, {"rows": [{"job": "hunting", "allowed": False, "deny_reason": DENY}]})
    result = _run(host, "claude", "-p", "second opinion", env={"ST_WORK_ROLE": "hunting", "AICO_PROJECT_ID": "neri-hunters"})
    assert result.returncode == 1
    assert result.stderr.strip() == f"agent-hub-cred-exec: claude-code: Claude is not allowed for hunting work: {DENY}"
    assert not host["report"].exists() and not _fetched(hub, "claude-code")
    rules = [(path, auth) for _, path, auth, _ in hub.requests if path.startswith("/api/models/")]
    assert rules == [("/api/models/launch-defaults?role=hunting&tool=claude-code&project=neri-hunters", None)]


def test_claude_credentials_go_to_an_allowed_work_role(host: dict[str, Any], hub: FakeHub) -> None:
    _claude_host(host, hub)
    result = _run(host, "claude", env={"ST_WORK_ROLE": "coordinator"})
    assert result.returncode == 0, result.stderr
    assert json.loads(host["report"].read_text())["claude"] == SECRET


@pytest.mark.parametrize("answer", [(500, {"error": "internal"}), (200, {"rows": [{"job": "hunting"}]}), "down"])
def test_without_the_rules_claude_is_refused_for_case_work_only(
    host: dict[str, Any], hub: FakeHub, answer: Any,
) -> None:
    _claude_host(host, hub)
    if answer != "down":
        hub.launch = answer
    for role, project in (("hunting", None), ("recon", "any-project"), ("verification", "neri-hunters")):
        env = {"ST_WORK_ROLE": role, **({"AICO_PROJECT_ID": project} if project else {}),
               **({"AGENT_HUB_URL": "http://127.0.0.1:9"} if answer == "down" else {})}
        result = _run(host, "claude", env=env)
        assert result.returncode == 1 and "launch rules could not be read" in result.stderr
        assert len(result.stderr.strip().splitlines()) == 1 and not host["report"].exists()
    assert not _fetched(hub, "claude-code")
    if answer != "down":  # the credential fetch itself needs Agent Hub
        assert _run(host, "claude", env={"ST_WORK_ROLE": "coordinator"}).returncode == 0


@pytest.mark.parametrize("project", [None, "neri", "agent-hub"])
def test_without_the_rules_verification_work_outside_neri_hunters_keeps_claude(
    host: dict[str, Any], hub: FakeHub, project: str | None,
) -> None:
    _claude_host(host, hub)
    hub.launch = (500, {"error": "internal"})
    env = {"ST_WORK_ROLE": "verification", **({"AICO_PROJECT_ID": project} if project else {})}
    result = _run(host, "claude", env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(host["report"].read_text())["claude"] == SECRET


def test_other_tools_and_sessions_without_a_work_role_are_not_checked(host: dict[str, Any], hub: FakeHub) -> None:
    _claude_host(host, hub)
    hub.launch = (200, {"rows": [{"allowed": False, "deny_reason": DENY}]})
    assert _run(host, "dummy-tool", env={"ST_WORK_ROLE": "hunting"}).returncode == 0
    assert _run(host, "claude").returncode == 0  # the owner's own use on the host
    assert not any(path.startswith("/api/models/") for _, path, _, _ in hub.requests)


PI_ROW = {"tool_slug": "pi", "name": "anthropic-key", "command": "pi", "config_dir": "~/.pi",
          "env_var": "ANTHROPIC_API_KEY", "auth_file": None, "rotates": False, "stored": True,
          "expired": False, "expires_at": None, "undecodable": False}


def _pi_host(host: dict[str, Any], hub: FakeHub) -> None:
    hub.rows.append(PI_ROW)
    hub.granted.append("pi")
    _install(host)


@pytest.mark.parametrize(("argv", "env"), [
    (["pi", "--model", "anthropic/claude-opus-5-5"], {}),
    (["pi", "--model=claude-sonnet-5-5"], {}),
])
def test_a_pi_session_running_a_claude_model_is_refused_like_claude_code(
    host: dict[str, Any], hub: FakeHub, argv: list[str], env: dict[str, str],
) -> None:
    _pi_host(host, hub)
    hub.launch = (200, {"rows": [{"job": "hunting", "allowed": False, "deny_reason": DENY}]})
    result = _run(host, *argv, env={"ST_WORK_ROLE": "hunting", "AICO_PROJECT_ID": "neri-hunters", **env})
    assert result.returncode == 1
    assert result.stderr.strip() == f"agent-hub-cred-exec: pi: Claude is not allowed for hunting work: {DENY}"
    assert not host["report"].exists() and not _fetched(hub, "pi")
    asked = [path for _, path, _, _ in hub.requests if path.startswith("/api/models/")]
    assert len(asked) == 1 and "tool=pi" in asked[0] and "model=" in asked[0] and "role=hunting" in asked[0]


@pytest.mark.parametrize(("argv", "env"), [
    (["pi", "--provider", "anthropic", "--model", "some-future-model"], {}),
    (["pi", "--provider=anthropic", "--model=some-future-model"], {}),
    (["pi"], {"AICO_ROOT_MODEL": "anthropic/some-future-model"}),
    (["pi", "--model", "claude-haiku-5-5"], {"AICO_ROOT_MODEL": "anthropic/claude-haiku-5-5"}),
])
def test_a_pi_session_on_the_anthropic_provider_is_claude_whatever_the_model_id(
    host: dict[str, Any], hub: FakeHub, argv: list[str], env: dict[str, str],
) -> None:
    _pi_host(host, hub)
    hub.launch = (200, {"rows": [{"job": "hunting", "allowed": False, "deny_reason": DENY}]})
    result = _run(host, *argv, env={"ST_WORK_ROLE": "hunting", "AICO_PROJECT_ID": "neri-hunters", **env})
    assert result.returncode == 1 and f"Claude is not allowed for hunting work: {DENY}" in result.stderr
    assert not host["report"].exists() and not _fetched(hub, "pi")
    assert [path for _, path, _, _ in hub.requests if path.startswith("/api/models/")] == [
        "/api/models/launch-defaults?role=hunting&tool=claude-code&project=neri-hunters"]


def test_a_pi_launch_names_provider_and_model_together_when_it_asks_agent_hub(host: dict[str, Any], hub: FakeHub) -> None:
    _pi_host(host, hub)
    hub.launch = (200, {"rows": [{"allowed": False, "deny_reason": DENY}]})
    _run(host, "pi", "--provider", "openai", "--model", "claude-lookalike", env={"ST_WORK_ROLE": "hunting"})
    asked = [path for _, path, _, _ in hub.requests if path.startswith("/api/models/")]
    assert asked == ["/api/models/launch-defaults?role=hunting&tool=pi&model=openai%2Fclaude-lookalike"]


@pytest.mark.parametrize("project", [None, "neri", "agent-hub"])
def test_without_the_rules_a_pi_verification_session_outside_neri_hunters_keeps_claude(
    host: dict[str, Any], hub: FakeHub, project: str | None,
) -> None:
    _pi_host(host, hub)
    hub.launch = (500, {"error": "internal"})
    env = {"ST_WORK_ROLE": "verification", **({"AICO_PROJECT_ID": project} if project else {})}
    assert _run(host, "pi", "--model", "anthropic/claude-opus-5-5", env=env).returncode == 0


def test_a_pi_session_on_another_model_or_an_allowed_role_is_not_refused(host: dict[str, Any], hub: FakeHub) -> None:
    _pi_host(host, hub)
    assert _run(host, "pi", "--model", "codex/gpt-6-sol", env={"ST_WORK_ROLE": "hunting"}).returncode == 0
    assert _run(host, "pi", env={"ST_WORK_ROLE": "hunting"}).returncode == 0  # no model known: not Claude
    assert not any("model=" in path for _, path, _, _ in hub.requests if path.startswith("/api/models/"))
    assert _run(host, "pi", "--model", "anthropic/claude-opus-5-5", env={"ST_WORK_ROLE": "coordinator"}).returncode == 0


@pytest.mark.parametrize("role", ["hunting", "recon", "verification"])
def test_without_the_rules_a_pi_session_on_a_claude_model_is_refused_for_case_work(
    host: dict[str, Any], hub: FakeHub, role: str,
) -> None:
    _pi_host(host, hub)
    hub.launch = (500, {"error": "internal"})
    result = _run(host, "pi", "--model", "anthropic/claude-opus-5-5", env={"ST_WORK_ROLE": role, "AICO_PROJECT_ID": "neri-hunters"})
    assert result.returncode == 1 and "launch rules could not be read" in result.stderr
    assert not _fetched(hub, "pi")
    assert _run(host, "pi", "--model", "codex/gpt-6-sol", env={"ST_WORK_ROLE": role}).returncode == 0


PI_LOGINS = {"anthropic": {"type": "oauth", "access": "anthropic-secret"}, "openai-codex": {"type": "oauth", "access": "codex-secret"},
             "opencode-go": {"type": "api_key", "key": "go-secret"}}
PI_FILE_ROW = {"tool_slug": "pi", "name": "logins", "command": "pi", "config_dir": "~/.pi", "env_var": None,
               "auth_file": "agent/auth.json", "rotates": False, "stored": True, "expired": False, "expires_at": None,
               "undecodable": False, "value": json.dumps(PI_LOGINS)}


def _pi_logins(host: dict[str, Any]) -> dict[str, Any]:
    return json.loads((host["home"] / ".pi/agent/auth.json").read_text())


def _pi_file_host(host: dict[str, Any], hub: FakeHub) -> None:
    hub.rows.append(PI_FILE_ROW)
    hub.granted.append("pi")
    _install(host)


@pytest.mark.parametrize("argv", [["pi"], ["pi", "--model", "codex/gpt-6-sol"], ["pi", "--provider", "openai", "--model", "gpt-6"]])
def test_a_denied_pi_session_on_another_model_gets_its_logins_without_anthropic(
    host: dict[str, Any], hub: FakeHub, argv: list[str],
) -> None:
    _pi_file_host(host, hub)
    hub.launch = (200, {"rows": [{"job": "hunting", "allowed": False, "deny_reason": DENY}]})
    result = _run(host, *argv, env={"ST_WORK_ROLE": "hunting", "AICO_PROJECT_ID": "neri-hunters"})
    assert result.returncode == 0, result.stderr
    assert set(_pi_logins(host)) == {"openai-codex", "opencode-go"}
    assert "anthropic-secret" not in (host["home"] / ".pi/agent/auth.json").read_text()
    assert "anthropic-secret" not in result.stdout + result.stderr


def test_a_denied_pi_session_gets_the_anthropic_env_var_withheld(host: dict[str, Any], hub: FakeHub) -> None:
    _pi_host(host, hub)  # the served login is ANTHROPIC_API_KEY
    hub.launch = (200, {"rows": [{"allowed": False, "deny_reason": DENY}]})
    assert _run(host, "pi", env={"ST_WORK_ROLE": "recon"}).returncode == 0
    assert json.loads(host["report"].read_text())["key"] is None


def test_pi_keeps_every_login_when_claude_is_allowed_or_there_is_no_work_role(host: dict[str, Any], hub: FakeHub) -> None:
    _pi_file_host(host, hub)
    assert _run(host, "pi", env={"ST_WORK_ROLE": "coordinator"}).returncode == 0
    assert set(_pi_logins(host)) == set(PI_LOGINS)
    hub.launch = (200, {"rows": [{"allowed": False, "deny_reason": DENY}]})
    assert _run(host, "pi").returncode == 0
    assert set(_pi_logins(host)) == set(PI_LOGINS)


def test_without_the_rules_a_pi_session_gets_no_anthropic_login_only_where_the_floor_applies(
    host: dict[str, Any], hub: FakeHub,
) -> None:
    _pi_file_host(host, hub)
    hub.launch = (500, {"error": "internal"})
    assert _run(host, "pi", env={"ST_WORK_ROLE": "hunting"}).returncode == 0
    assert "anthropic" not in _pi_logins(host)
    assert _run(host, "pi", env={"ST_WORK_ROLE": "verification", "AICO_PROJECT_ID": "neri-hunters"}).returncode == 0
    assert "anthropic" not in _pi_logins(host)
    assert _run(host, "pi", env={"ST_WORK_ROLE": "verification", "AICO_PROJECT_ID": "agent-hub"}).returncode == 0
    assert "anthropic" in _pi_logins(host)
