"""Session records from a remote agent host: the host CLI against a fake Agent Hub."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

REMOTE_CLI = Path(__file__).resolve().parents[3] / "integrations/context-delivery/bin/agent-hub-context-remote"
TOKEN = "host-token-" + "z" * 20
SID = "00000000-0000-4000-8000-000000000001"


class FakeHub:
    """The host-session routes, keeping each copy in memory."""

    def __init__(self) -> None:
        self.copies: dict[str, bytes] = {}
        self.requests: list[dict[str, Any]] = []
        self.sync_status = 200


@pytest.fixture
def hub() -> Iterator[tuple[str, FakeHub]]:
    state = FakeHub()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, status: int, body: Any) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _route(self, method: str) -> None:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            state.requests.append({"method": method, "path": url.path, "query": query, "raw": raw,
                                   "auth": self.headers.get("Authorization")})
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._answer(401, {"error": "http_error", "message": "Unknown or revoked host token", "details": []})
            if url.path.startswith("/api/host-sessions/transcripts/"):
                key = url.path.rsplit("/transcripts/", 1)[1] + ":" + query["path"]
                copy = state.copies.get(key, b"")
                if method == "GET":
                    return self._answer(200, {"size": len(copy)})
                if int(query["offset"]) != len(copy):
                    return self._answer(409, {"error": "offset_mismatch", "message": "x", "details": [{"size": len(copy)}]})
                state.copies[key] = copy + raw
                return self._answer(200, {"size": len(state.copies[key])})
            if url.path == "/api/host-sessions/sync":
                if state.sync_status != 200:
                    return self._answer(state.sync_status, {"error": "unregistered_cwd", "message": "x", "details": []})
                body = json.loads(raw)
                return self._answer(200, {"session_id": body["session_id"], "events_appended": 1})
            if url.path == "/api/host-sessions/work-role":
                self.send_response(204)
                self.end_headers()
                return None
            if url.path == "/api/host-sessions/retire-pi":
                return self._answer(200, {"closed_session_ids": [], "unavailable_session_ids": []})
            return self._answer(404, {"detail": "Not Found"})

        def do_GET(self) -> None:
            self._route("GET")

        def do_POST(self) -> None:
            self._route("POST")

        def log_message(self, *_args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / ".config/agent-hub").mkdir(parents=True)
    (tmp_path / ".config/agent-hub/host-token").write_text(TOKEN + "\n", encoding="utf-8")
    return tmp_path


def _run(home: Path, url: str, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {"HOME": str(home), "AGENT_HUB_URL": url, "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(REMOTE_CLI), *argv], env=env, capture_output=True, text=True,
                          timeout=30, check=False)


def _requests(state: FakeHub, path: str) -> list[dict[str, Any]]:
    return [request for request in state.requests if request["path"] == path]


def test_sync_pi_sends_only_new_bytes_then_asks_for_the_record(home: Path, hub: tuple[str, FakeHub]) -> None:
    url, state = hub
    transcript = home / ".pi/agent/sessions/--srv-workspaces-projects-agent-hub--" / f"2026_{SID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "session", "id": SID}) + "\n", encoding="utf-8")
    args = ("sync-pi", "--transcript", str(transcript), "--session", SID, "--cwd", "/srv/workspaces/projects/agent-hub",
            "--provider", "opencode-go", "--model", "deepseek-v4.1-flash", "--phase", "working",
            "--aico-session", "aico-widget-1234abcd", "--work-role-json", '{"id":"implementation","source":"tether:root:x"}')

    first = _run(home, url, *args)
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"message","id":"m1"}\n')
    second = _run(home, url, *args)

    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert json.loads(first.stdout)["session_id"] == SID
    [copy] = state.copies.values()
    assert copy == transcript.read_bytes()
    appends = [r for r in state.requests if r["method"] == "POST" and "/transcripts/" in r["path"]]
    assert [r["query"]["offset"] for r in appends] == ["0", str(len(copy) - len('{"type":"message","id":"m1"}\n'))]
    assert appends[0]["path"] == f"/api/host-sessions/transcripts/pi/{SID}"
    assert appends[0]["query"]["path"] == f"--srv-workspaces-projects-agent-hub--/2026_{SID}.jsonl"
    sync = json.loads(_requests(state, "/api/host-sessions/sync")[-1]["raw"])
    assert sync == {"surface": "pi", "session_id": SID, "path": appends[0]["query"]["path"],
                    "cwd": "/srv/workspaces/projects/agent-hub", "provider": "opencode-go",
                    "model": "deepseek-v4.1-flash", "phase": "working", "aico_session_id": "aico-widget-1234abcd",
                    "work_role": {"id": "implementation", "source": "tether:root:x"}}
    assert TOKEN not in first.stdout + first.stderr


def test_large_transcripts_go_in_pieces(home: Path, hub: tuple[str, FakeHub]) -> None:
    url, state = hub
    transcript = home / ".claude/projects/-srv-workspaces-projects-agent-hub" / f"{SID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes((b'{"type":"user","pad":"' + b"x" * 1000 + b'"}\n') * 5000)  # ~5 MB
    result = _run(home, url, "sync-transcript", "--surface", "claude_code", "--session", SID, "--transcript",
                  str(transcript), "--cwd", "/srv/workspaces/projects/agent-hub", "--finalize")
    assert result.returncode == 0, result.stderr
    appends = [r for r in state.requests if r["method"] == "POST" and "/transcripts/" in r["path"]]
    assert len(appends) == 3 and max(len(r["raw"]) for r in appends) <= 2 * 1024 * 1024
    assert list(state.copies.values()) == [transcript.read_bytes()]
    assert json.loads(_requests(state, "/api/host-sessions/sync")[0]["raw"])["finalize"] is True


def test_bind_and_retire_post_to_the_host_routes(home: Path, hub: tuple[str, FakeHub]) -> None:
    url, state = hub
    bound = _run(home, url, "bind-native-work-role", "--surface", "claude_code", "--session", SID, "--cwd", "/srv",
                 "--model", "claude-opus-5-5", "--work-role-json", '{"id":"coordinator","source":"tether:root:x"}')
    retired = _run(home, url, "retire-pi", "--aico-session", "aico-widget-1234abcd")
    assert bound.returncode == retired.returncode == 0, bound.stderr + retired.stderr
    [role] = _requests(state, "/api/host-sessions/work-role")
    assert json.loads(role["raw"])["work_role"] == {"id": "coordinator", "source": "tether:root:x"}
    assert json.loads(_requests(state, "/api/host-sessions/retire-pi")[0]["raw"]) == {
        "aico_session_id": "aico-widget-1234abcd"}


def test_failures_are_one_line_and_exit_2_like_the_local_cli(home: Path, hub: tuple[str, FakeHub], tmp_path: Path) -> None:
    url, _state = hub
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    wrong_place = _run(home, url, "sync-pi", "--transcript", str(outside), "--session", SID, "--cwd", "/",
                       "--provider", "p", "--model", "m")
    (home / ".config/agent-hub/host-token").unlink()
    no_token = _run(home, url, "bind-native-work-role", "--surface", "codex", "--session", SID, "--cwd", "/",
                    "--work-role-json", "{}")
    dead_link = _run(home, "http://127.0.0.1:9", "retire-pi", "--aico-session", "aico-widget-1234abcd")
    for result, line in ((wrong_place, "Pi session sync unavailable"),
                         (no_token, "Native session work role registration unavailable"),
                         (dead_link, "Pi retirement sync unavailable")):
        assert result.returncode == 2
        assert result.stderr.startswith(line) and len(result.stderr.strip().splitlines()) == 1
        assert "Traceback" not in result.stderr


def _rollout(home: Path, session: str, **meta: Any) -> Path:
    path = home / ".codex/sessions/2026/10/30" / f"rollout-2026-10-30T10-00-00-{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"type": "session_meta", "payload": {"id": session, "cwd": "/srv/workspaces/projects/agent-hub", **meta}}
    path.write_text(json.dumps(header) + "\n", encoding="utf-8")
    return path


def test_sync_codex_records_parents_first_closes_finished_rollouts_once(home: Path, hub: tuple[str, FakeHub]) -> None:
    url, state = hub
    child = "00000000-0000-4000-8000-0000000000c1"
    _rollout(home, child, parent_thread_id=SID)
    _rollout(home, SID)

    first = _run(home, url, "sync-codex")
    second = _run(home, url, "sync-codex")

    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    syncs = [json.loads(request["raw"]) for request in _requests(state, "/api/host-sessions/sync")]
    assert [body["session_id"] for body in syncs] == [SID, child]  # nothing changed for the second run
    assert all(body["surface"] == "codex" and body["finalize"] is True for body in syncs)  # no process holds them


def test_sync_codex_skips_threads_outside_projects_without_failing(home: Path, hub: tuple[str, FakeHub]) -> None:
    url, state = hub
    state.sync_status = 400
    _rollout(home, SID)
    assert _run(home, url, "sync-codex").returncode == 0
    assert _run(home, url, "sync-codex").returncode == 0
    assert len(_requests(state, "/api/host-sessions/sync")) == 1
