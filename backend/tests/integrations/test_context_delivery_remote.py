"""Context delivery from a remote agent host: the HTTP CLI and the host-token route."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api import host_context
from app.cli.runtime_context import _build_parser, delivery_request
from app.services.runtime_context import CanonicalContextDeliveryRequest
from app.storage.remote_hosts import HostIdentity

REMOTE_CLI = Path(__file__).resolve().parents[3] / "integrations/context-delivery/bin/agent-hub-context-remote"
TOKEN = "host-token-" + "x" * 20
ARGV = [
    "deliver", "--surface", "claude_code", "--profile", "agent_startup", "--capability", "hooks",
    "--agent-slug", " coder ", "--project", "agent-hub", "--session", "s-1", "--cwd", "/srv/workspaces/projects/agent-hub",
    "--provider", "anthropic", "--model", "claude-opus-5-5", "--hook-event", "SessionStart", "--source", "startup",
    "--metadata", "aico_session_id=abc", "--metadata", "empty=", "--workflow", "wf", "--source-id", "src",
    "--consumer-tag", "tag", "--optional-context", "off", "--format", "json",
]


def _remote() -> Any:
    return SourceFileLoader("agent_hub_context_remote", str(REMOTE_CLI)).load_module()


@pytest.mark.parametrize("argv", [ARGV, ["deliver", "--surface", "codex_cli"]])
def test_remote_cli_builds_the_request_the_database_cli_builds(argv: list[str]) -> None:
    remote = _remote()
    sent = remote.delivery_request(remote._parser().parse_args(argv))
    expected = delivery_request(_build_parser().parse_args(argv))
    assert CanonicalContextDeliveryRequest.model_validate(sent) == expected


@pytest.fixture
def agent_hub() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            ok = self.headers.get("Authorization") == f"Bearer {TOKEN}"
            payload = json.dumps({"status": "ok", "rendered": "context for the host\n"}).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()


def _run(env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REMOTE_CLI), *argv], env=env, capture_output=True, text=True, timeout=30, check=False
    )


def test_remote_cli_posts_with_the_host_token_and_prints_the_rendered_context(
    tmp_path: Path, agent_hub: tuple[str, list[dict[str, Any]]]
) -> None:
    url, seen = agent_hub
    token_file = tmp_path / "host-token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    env = {"AGENT_HUB_URL": url, "AGENT_HUB_HOST_TOKEN_FILE": str(token_file), "PATH": "/usr/bin:/bin"}

    result = _run(env, "deliver", "--surface", "claude_code", "--project", "agent-hub")

    assert (result.returncode, result.stdout) == (0, "context for the host\n")
    assert seen[0]["path"] == "/api/host-context/deliver"
    assert seen[0]["auth"] == f"Bearer {TOKEN}"
    assert seen[0]["body"]["project_id"] == "agent-hub"
    assert TOKEN not in result.stdout + result.stderr


def test_remote_cli_fails_clearly_without_a_token_or_a_reachable_hub(
    tmp_path: Path, agent_hub: tuple[str, list[dict[str, Any]]]
) -> None:
    url, seen = agent_hub
    missing = _run({"AGENT_HUB_URL": url, "AGENT_HUB_HOST_TOKEN_FILE": str(tmp_path / "none")}, "deliver", "--surface", "x")
    assert missing.returncode == 2 and "no host token" in missing.stderr and not seen

    wrong = tmp_path / "wrong"
    wrong.write_text("not-the-token", encoding="utf-8")
    refused = _run({"AGENT_HUB_URL": url, "AGENT_HUB_HOST_TOKEN_FILE": str(wrong)}, "deliver", "--surface", "x")
    assert refused.returncode == 2 and "HTTP 401" in refused.stderr and "not-the-token" not in refused.stderr

    local_only = _run({}, "sync-pi", "--session", "s")
    assert local_only.returncode == 2 and "unavailable on a remote host" in local_only.stderr


async def test_host_route_records_which_host_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[CanonicalContextDeliveryRequest] = []

    async def fake_build(_db: object, request: CanonicalContextDeliveryRequest) -> str:
        built.append(request)
        return "delivered"

    monkeypatch.setattr(host_context, "build_canonical_context_delivery", fake_build)
    request = CanonicalContextDeliveryRequest(
        consumer_surface="claude_code", client_metadata={"remote_host": "spoofed", "source": "startup"}
    )

    result = await host_context.deliver_host_context(request, HostIdentity("agent-work", ()), db=object())  # type: ignore[arg-type]

    assert result == "delivered"
    assert built[0].client_metadata == {"remote_host": "agent-work", "source": "startup"}
    assert request.client_metadata["remote_host"] == "spoofed"




async def fake_require_host(request: Request) -> HostIdentity:
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Unknown or revoked host token")
    return HostIdentity("agent-work", ())


async def no_db() -> Any:
    yield None


async def test_host_route_is_served_through_the_app_only_with_a_host_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.api.remote_hosts import require_host
    from app.db import get_db
    from app.main import app
    from app.middleware.access_control_paths import is_path_exempt

    async def fake_build(_db: object, request: CanonicalContextDeliveryRequest) -> Any:
        # A distinct status proves the request reached delivery, for this host.
        raise HTTPException(status_code=418, detail=request.client_metadata["remote_host"])

    monkeypatch.setattr(host_context, "build_canonical_context_delivery", fake_build)
    app.dependency_overrides[require_host] = fake_require_host
    app.dependency_overrides[get_db] = no_db
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
            body = {"consumer_surface": "claude_code"}
            refused = await http.post("/api/host-context/deliver", json=body)
            served = await http.post("/api/host-context/deliver", json=body, headers={"Authorization": f"Bearer {TOKEN}"})
    finally:
        app.dependency_overrides.pop(require_host, None)
        app.dependency_overrides.pop(get_db, None)

    assert is_path_exempt("/api/host-context/deliver")
    assert refused.status_code == 401
    assert served.status_code == 418 and "agent-work" in served.text


@pytest.fixture
def truncating_hub() -> Iterator[str]:
    """An HTTP server that promises a longer body than it sends, then hangs up."""
    import socket

    server = socket.create_server(("127.0.0.1", 0))

    def serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(65536)
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{"status": "o')

    threading.Thread(target=serve, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}"
    finally:
        server.close()


def test_remote_cli_answers_a_truncated_reply_with_one_line_and_exit_2(tmp_path: Path, truncating_hub: str) -> None:
    token_file = tmp_path / "host-token"
    token_file.write_text(TOKEN, encoding="utf-8")
    result = _run({"AGENT_HUB_URL": truncating_hub, "AGENT_HUB_HOST_TOKEN_FILE": str(token_file)}, "deliver", "--surface", "x")
    assert result.returncode == 2
    assert len(result.stderr.strip().splitlines()) == 1 and "Traceback" not in result.stderr


def test_remote_cli_never_sends_the_host_token_through_an_environment_proxy(
    tmp_path: Path, agent_hub: tuple[str, list[dict[str, Any]]]
) -> None:
    url, seen = agent_hub
    token_file = tmp_path / "host-token"
    token_file.write_text(TOKEN, encoding="utf-8")
    proxy = "http://127.0.0.1:9"  # nothing listens: a proxied request would fail
    env = {"AGENT_HUB_URL": url, "AGENT_HUB_HOST_TOKEN_FILE": str(token_file), "PATH": "/usr/bin:/bin",
           "http_proxy": proxy, "HTTP_PROXY": proxy, "all_proxy": proxy}
    result = _run(env, "deliver", "--surface", "claude_code")
    assert result.returncode == 0, result.stderr
    assert seen[0]["auth"] == f"Bearer {TOKEN}"
