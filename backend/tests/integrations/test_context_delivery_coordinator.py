"""The context client tags Tether-flagged coordinator widgets for delivery."""

from __future__ import annotations

import http.server
import json
import os
import runpy
import shutil
import socketserver
import stat
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.private_context

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT = REPO_ROOT / "integrations/context-delivery/bin/agent-hub-context-client"
WIDGET = "c0ffee12"

FAKE_CLI = """#!/usr/bin/env python3
import hashlib, json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_ARGV_LOG"], "w", encoding="utf-8") as handle:
    json.dump(args, handle)
rendered = "canonical context"
digest = hashlib.sha256(rendered.encode()).hexdigest()
print(json.dumps({
    "schema_version": "agent-hub.context.v1", "context_version": "1", "delivery_id": "d1",
    "artifact_id": "context-" + digest, "generated_at": "2026-10-16T00:00:00Z", "status": "ok",
    "delivery_mode": "additive", "recommended_role": "developer", "native_context_policy": "preserve",
    "precedence": "preserve", "payload_hash_algorithm": "sha256", "payload_hash": digest,
    "metadata": {"consumer_surface": args[args.index("--surface") + 1], "session_id": "s"},
    "blocks": [], "rendered": rendered, "estimated_tokens": 4,
    "required_policy": {"state": "complete", "required_source_ids": [], "delivered_source_ids": [],
                        "missing_source_ids": [], "pending_review_source_ids": []},
    "failure": None,
}))
"""


class _Tether(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    descriptors: dict[str, dict]
    requests: list[str]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server: _Tether = self.server  # type: ignore[assignment]
        server.requests.append(self.path)
        descriptor = server.descriptors.get(self.path.rsplit("/", 1)[-1])
        body = json.dumps(descriptor or {"error": "not_found"}).encode()
        self.send_response(200 if descriptor else 404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def address_string(self) -> str:
        return "tether-test"

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def tether() -> Iterator[_Tether]:
    directory = tempfile.mkdtemp(prefix="th-")  # AF_UNIX paths stay short
    server = _Tether(os.path.join(directory, "control.sock"), _Handler)
    server.descriptors = {}
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(directory, ignore_errors=True)


def _descriptor(coordinator: bool) -> dict:
    return {"id": WIDGET, "status": "running", "coordinator": coordinator, "coordinatorId": None}


def _client() -> dict:
    return runpy.run_path(str(CLIENT))


def test_lookup_reads_the_coordinator_flag(tether: _Tether, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TETHER_SOCKET", tether.server_address)
    lookup = _client()["_tether_coordinator"]
    tether.descriptors[WIDGET] = _descriptor(True)
    assert lookup(WIDGET) is True
    tether.descriptors[WIDGET] = _descriptor(False)
    assert lookup(WIDGET) is False
    assert lookup("0badf00d") is False  # unknown widget: 404
    assert tether.requests == [f"/v1/sessions/{WIDGET}", f"/v1/sessions/{WIDGET}", "/v1/sessions/0badf00d"]


def test_lookup_never_queries_for_missing_or_malformed_ids(tether: _Tether, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TETHER_SOCKET", tether.server_address)
    lookup = _client()["_tether_coordinator"]
    for widget in (None, "", "widget-7", "C0FFEE12", "../v1/x"):
        assert lookup(widget) is False
    assert tether.requests == []


def test_lookup_treats_missing_tether_as_plain_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TETHER_SOCKET", str(tmp_path / "absent.sock"))
    assert _client()["_tether_coordinator"](WIDGET) is False


def _deliver(tmp_path: Path, tether: _Tether, command: str = "deliver") -> list[str]:
    cli = tmp_path / "agent-hub-context"
    cli.write_text(FAKE_CLI, encoding="utf-8")
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "argv.json"
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("AICO_", "AGENT_HUB_CONTEXT_PREINJECTED", "ST_WORK_ROLE"))
    }
    env.update({
        "AGENT_HUB_CONTEXT_CLI": str(cli),
        "FAKE_ARGV_LOG": str(log),
        "AICO_WIDGET_ID": WIDGET,
        "TETHER_SOCKET": str(tether.server_address),
    })
    subprocess.run(
        [str(CLIENT), command, "--surface", "claude_code", "--cwd", str(tmp_path),
         "--session", "s", "--artifact-root", str(tmp_path / "artifacts")],
        env=env, check=True, capture_output=True, text=True, timeout=60,
        input="{}" if command == "hook" else None,
    )
    return json.loads(log.read_text())


def _tags(argv: list[str]) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv) if value == "--consumer-tag"]


@pytest.mark.parametrize("command", ["deliver", "hook"])
def test_coordinator_widget_delivery_carries_the_tag(tmp_path: Path, tether: _Tether, command: str) -> None:
    tether.descriptors[WIDGET] = _descriptor(True)
    assert _tags(_deliver(tmp_path, tether, command)) == ["aico-coordinator"]


def test_plain_widget_delivery_has_no_tag(tmp_path: Path, tether: _Tether) -> None:
    tether.descriptors[WIDGET] = _descriptor(False)
    assert _tags(_deliver(tmp_path, tether)) == []


def test_bind_does_not_query_tether(tmp_path: Path, tether: _Tether) -> None:
    tether.descriptors[WIDGET] = _descriptor(True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("AICO_", "AGENT_HUB_CONTEXT_PREINJECTED"))}
    env.update({"AICO_WIDGET_ID": WIDGET, "TETHER_SOCKET": str(tether.server_address)})
    subprocess.run(
        [str(CLIENT), "bind", "--surface", "claude_code", "--cwd", str(tmp_path), "--artifact-root", str(tmp_path / "a")],
        env=env, check=False, capture_output=True, text=True, timeout=60, input="{}",
    )
    assert tether.requests == []
