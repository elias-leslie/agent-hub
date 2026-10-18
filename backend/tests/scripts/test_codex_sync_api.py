from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import cast

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_api = importlib.import_module("codex_sync_api")


class _Response:
    status = 200

    def __init__(self, payload: str = "{}") -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.payload.encode("utf-8")


def test_post_json_uses_approved_client_id_headers_without_secret(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured["request"] = req
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(codex_sync_api.request, "urlopen", fake_urlopen)

    status, _ = codex_sync_api.post_json(
        "http://agent-hub.test/api",
        "/sessions",
        {"ok": True},
        "summitflow",
        "/srv/workspaces/projects/agent-hub/scripts/codex-session-sync.py",
    )

    headers = {key.lower(): value for key, value in captured["request"].header_items()}
    assert status == 200
    assert headers["x-client-id"] == "summitflow"
    assert headers["x-request-source"] == "codex-transcript-sync"
    assert headers["x-source-client"] == "agent-hub/codex-session-sync"
    assert "x-client-secret" not in headers


def test_upsert_passes_parent_and_external_identity(monkeypatch) -> None:
    bodies: list[dict[str, object]] = []

    def fake_urlopen(req, timeout):
        del timeout
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(codex_sync_api.request, "urlopen", fake_urlopen)
    external_identity = {
        "harness": "codex",
        "launcher": "aico",
        "display_identity": "Leibniz",
        "runtime_session_id": "child-session",
        "agent_path": "/root/aico_session_federation",
        "aico_session_id": "aico-widget-35f62654",
        "aico_widget_id": "35f62654",
        "aico_project_id": "a-loom",
        "project_mapping_state": "matched",
    }

    ok, _, _ = codex_sync_api.upsert_session(
        "child-session",
        {
            "project_id": "a-loom",
            "branch": "main",
            "repo_root": "/srv/workspaces/projects/a-loom",
        },
        "gpt-5.4",
        Path("/srv/workspaces/projects/a-loom"),
        Path("/tmp/child.jsonl"),
        "http://agent-hub.test/api",
        "summitflow",
        parent_session_id="parent-session",
        provider_metadata={"external_identity": external_identity},
    )

    assert ok
    assert bodies[0]["parent_session_id"] == "parent-session"
    metadata = cast(dict[str, object], bodies[0]["provider_metadata"])
    assert metadata["external_identity"] == external_identity


def test_heartbeat_does_not_clobber_event_derived_phase_or_status(monkeypatch) -> None:
    bodies: list[dict[str, object]] = []

    def fake_urlopen(req, timeout):
        del timeout
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(codex_sync_api.request, "urlopen", fake_urlopen)

    ok, _, _ = codex_sync_api.send_heartbeat(
        "child-session",
        Path("/srv/workspaces/projects/a-loom"),
        {"branch": "main"},
        {"external_identity": {"runtime_session_id": "child-session"}},
        "http://agent-hub.test/api",
        "summitflow",
    )

    assert ok
    assert "phase" not in bodies[0]
    assert "status" not in bodies[0]
    assert "summary" not in bodies[0]
    assert "last_event_type" not in bodies[0]
