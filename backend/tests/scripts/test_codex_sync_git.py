from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_git = importlib.import_module("codex_sync_git")


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._body = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body.read()


def test_fetch_registered_project_root_uses_exact_registry_record(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    token_file = tmp_path / "owner-token"
    token_file.write_text("owner-s3cret\n")
    monkeypatch.setenv("SUMMITFLOW_OWNER_TOKEN_FILE", str(token_file))

    def fake_urlopen(req, timeout: int):
        captured.update(url=req.full_url, timeout=timeout, token=req.get_header("X-summitflow-owner-token"))
        return _Response(b'{"id":"rootfall","root_path":"/srv/workspaces/projects/rootfall"}')

    monkeypatch.setattr(codex_sync_git.request, "urlopen", fake_urlopen)

    root = codex_sync_git.fetch_registered_project_root(
        "rootfall",
        "http://summitflow.test/api",
    )

    assert root == Path("/srv/workspaces/projects/rootfall")
    assert captured == {
        "url": "http://summitflow.test/api/projects/rootfall",
        "timeout": codex_sync_git.REGISTRY_TIMEOUT_SECONDS,
        "token": "owner-s3cret",
    }


def test_fetch_registered_project_root_rejects_unsafe_id_without_request(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        codex_sync_git.request,
        "urlopen",
        lambda *_args, **_kwargs: calls.append(object()),
    )

    assert codex_sync_git.fetch_registered_project_root("../rootfall") is None
    assert calls == []
