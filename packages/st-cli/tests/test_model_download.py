"""The managed relay preserves native bytes without exposing upstream URLs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager

import httpx
import pytest
from st_sdk.usage import collect_usage_specs
from typer.testing import CliRunner

from agent_hub_st import model_download as download
from agent_hub_st import model_download_registry as relay
from agent_hub_st import models

BLOB = b"model-bytes"
DIGEST = "sha256:" + hashlib.sha256(BLOB).hexdigest()
MANIFEST = json.dumps({"config": {"digest": DIGEST}, "layers": [{"digest": DIGEST}], "extra": "retained"}).encode()
CLIENT = httpx.Client


def registry(monkeypatch, requests):
    def respond(request):
        requests.append(request)
        assert not request.headers.get("Authorization")
        assert not request.headers.get("Cookie")
        if "/manifests/" in request.url.path:
            return httpx.Response(200, content=MANIFEST)
        if request.url.host == "registry.example":
            return httpx.Response(307, headers={"Location": "https://cdn.example/data?private=hidden"})
        if request.headers.get("Range") == "bytes=2-5":
            return httpx.Response(206, headers={"Content-Range": "bytes 2-5/11", "Content-Length": "4"}, stream=httpx.ByteStream(BLOB[2:6]))
        return httpx.Response(200, headers={"Content-Length": str(len(BLOB))}, stream=httpx.ByteStream(BLOB))

    monkeypatch.setattr(relay.httpx, "Client", lambda **kwargs: CLIENT(transport=httpx.MockTransport(respond), **kwargs))
    return relay.Registry("tiny:v1", "https://registry.example")


def test_relay_freezes_manifest_restricts_paths_and_closes_listener(monkeypatch):
    requests = []
    reg = registry(monkeypatch, requests)
    with reg.serve() as temporary, CLIENT(trust_env=False) as client:
        origin = "http://" + temporary.split("/")[0]
        response = client.get(origin + reg.manifest_path)
        assert response.content == MANIFEST
        assert response.headers["Docker-Content-Digest"] == reg.digest
        assert client.head(origin + reg.manifest_path).headers["Content-Length"] == str(len(MANIFEST))
        for path in ("/v2/other/tiny/manifests/v1", "/v2/library/tiny/manifests/other", "/v2/library/tiny/blobs/sha256:" + "0" * 64, reg.manifest_path + "?url=https://example.com"):
            assert client.get(origin + path).status_code == 404
        assert len(requests) == 1
    reg.close()
    with pytest.raises(httpx.ConnectError):
        CLIENT(trust_env=False).get(origin + "/v2/")


def test_blob_head_get_and_ranges_keep_redirects_local(monkeypatch):
    requests = []
    reg = registry(monkeypatch, requests)
    with reg.serve() as temporary, CLIENT(trust_env=False) as client:
        origin = "http://" + temporary.split("/")[0]
        path = f"/v2/library/tiny/blobs/{DIGEST}"
        response = client.get(origin + path)
        assert response.content == BLOB
        assert response.headers["Location"] == origin + path
        assert "hidden" not in str(response.headers)
        assert client.head(origin + path).content == b""
        ranged = client.get(origin + path, headers={"Range": "bytes=2-5"})
        assert (ranged.status_code, ranged.content) == (206, BLOB[2:6])
        assert ranged.headers["Content-Range"] == "bytes 2-5/11"
        count = len(requests)
        assert client.get(origin + path, headers={"Range": "bytes=0-1,4-5"}).status_code == 416
        assert len(requests) == count
    reg.close()


@pytest.mark.parametrize("model", ["https://example.com/m", "localhost:123/a", "../tiny", "a/b/c", "tiny?url=x", "tiny@sha256:abc"])
def test_rejects_non_public_model_names(model):
    with pytest.raises(ValueError):
        relay.model_name(model)


def test_rejects_non_https_redirect_without_forwarding_challenge(monkeypatch):
    requests = []
    reg = registry(monkeypatch, requests)
    reg.client.close()
    reg.client = CLIENT(transport=httpx.MockTransport(lambda request: httpx.Response(307, headers={"Location": "http://localhost/private", "WWW-Authenticate": "secret"})))
    with reg.serve() as temporary, CLIENT(trust_env=False) as client:
        response = client.get("http://" + temporary.split("/")[0] + f"/v2/library/tiny/blobs/{DIGEST}")
        assert response.status_code == 502
        assert "WWW-Authenticate" not in response.headers
        assert "localhost/private" not in response.text
    reg.close()


class FakeRegistry:
    digest = DIGEST
    closed = False
    stopped = False

    def __init__(self, *args):
        pass

    @contextmanager
    def serve(self):
        try:
            yield "127.0.0.1:12345/library/tiny:latest"
        finally:
            self.stopped = True

    def close(self):
        self.closed = True


@pytest.mark.parametrize("failure", [None, "pull", "cp", "cancel", "verify"])
def test_native_copy_identity_and_exact_cleanup(monkeypatch, failure):
    reg = FakeRegistry()
    monkeypatch.setattr(download, "Registry", lambda *args: reg)
    state = {}
    temporary = "127.0.0.1:12345/library/tiny:latest"
    monkeypatch.setattr(download, "installed_models", lambda endpoint: state)
    calls = []
    digests = iter([None, None, "wrong" if failure == "verify" else DIGEST])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))

    def native(endpoint, *args, **kwargs):
        calls.append(args)
        if args[0] == failure:
            raise subprocess.CalledProcessError(1, "ollama")
        if failure == "cancel" and args[0] == "pull":
            raise KeyboardInterrupt
        if args[0] == "pull":
            state[temporary] = DIGEST

    monkeypatch.setattr(download, "native", native)
    if failure:
        with pytest.raises((subprocess.CalledProcessError, KeyboardInterrupt, ValueError)):
            download.pull("tiny")
    else:
        download.pull("tiny")
        assert calls[1] == ("cp", "127.0.0.1:12345/library/tiny:latest", "tiny")
    assert calls[0] == ("pull", "--insecure", "127.0.0.1:12345/library/tiny:latest")
    if failure in ("pull", "cancel"):
        assert len(calls) == 1  # No alias was installed, so cleanup has nothing to remove.
    else:
        assert calls[-1] == ("rm", temporary)
    assert reg.closed and reg.stopped


def test_existing_destination_is_never_overwritten(monkeypatch):
    reg = FakeRegistry()
    monkeypatch.setattr(download, "Registry", lambda *args: reg)
    monkeypatch.setattr(download, "installed_digest", lambda *args: "existing")
    monkeypatch.setattr(download, "native", lambda *args, **kwargs: pytest.fail("native mutation"))
    with pytest.raises(ValueError, match="already contains"):
        download.pull("tiny")
    assert reg.closed


def test_ollama_bare_manifest_digest_is_normalized(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "tiny:latest", "digest": DIGEST.removeprefix("sha256:")}]}))
    monkeypatch.setattr(download.httpx, "Client", lambda **kwargs: CLIENT(transport=transport, **kwargs))
    assert download.installed_digest("http://127.0.0.1:11434", "library/tiny") == DIGEST


def test_local_collisions_ignore_case_without_changing_upstream_tag(monkeypatch):
    fetched = []
    monkeypatch.setattr(download, "Registry", lambda model, base: fetched.append(model) or FakeRegistry())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "TiNy:v1", "digest": "0" * 64}]}))
    monkeypatch.setattr(download.httpx, "Client", lambda **kwargs: CLIENT(transport=transport, **kwargs))
    monkeypatch.setattr(download, "native", lambda *args, **kwargs: pytest.fail("must preserve different destination"))
    with pytest.raises(ValueError, match="already contains"):
        download.pull("tiny:V1")
    assert fetched == ["tiny:V1"]
    assert relay.model_name("tiny:V1") == ("library/tiny", "V1")


@pytest.mark.parametrize("collision", ["destination", "temporary"])
def test_concurrent_destination_and_stale_temporary_alias_are_preserved(monkeypatch, collision):
    reg = FakeRegistry()
    monkeypatch.setattr(download, "Registry", lambda *args: reg)
    digests = iter([None, "appeared"])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))
    temporary = "127.0.0.1:12345/library/tiny:latest"
    state = {temporary: DIGEST} if collision == "temporary" else {}
    monkeypatch.setattr(download, "installed_models", lambda endpoint: state)
    calls = []

    def native(endpoint, *args, **kwargs):
        calls.append(args)
        if args[0] == "pull":
            state[temporary] = DIGEST

    monkeypatch.setattr(download, "native", native)
    with pytest.raises(ValueError, match="leaving it unchanged"):
        download.pull("tiny")
    assert not any(call[0] == "cp" for call in calls)
    assert calls == [] if collision == "temporary" else calls[-1] == ("rm", temporary)
    assert reg.closed and reg.stopped


def test_cleanup_failure_is_reported_as_failure(monkeypatch):
    monkeypatch.setattr(download, "Registry", lambda *args: FakeRegistry())
    state = {}
    temporary = "127.0.0.1:12345/library/tiny:latest"
    monkeypatch.setattr(download, "installed_models", lambda endpoint: state)
    digests = iter([None, None, DIGEST])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))

    def native(endpoint, *args, **kwargs):
        if args[0] == "pull":
            state[temporary] = DIGEST
        if args[0] == "rm":
            raise subprocess.CalledProcessError(1, "ollama")

    monkeypatch.setattr(download, "native", native)
    with pytest.raises(ValueError, match="cleanup incomplete"):
        download.pull("tiny")


@pytest.mark.parametrize("changed_at", ["pull", "cp"])
def test_changed_temporary_alias_is_never_copied_or_removed(monkeypatch, changed_at):
    monkeypatch.setattr(download, "Registry", lambda *args: FakeRegistry())
    temporary = "127.0.0.1:12345/library/tiny:latest"
    state = {}
    monkeypatch.setattr(download, "installed_models", lambda endpoint: state)
    monkeypatch.setattr(download, "installed_digest", lambda *args: None)
    calls = []

    def native(endpoint, *args, **kwargs):
        calls.append(args)
        if args[0] == "pull":
            state[temporary] = DIGEST
        if args[0] == changed_at:
            state[temporary] = "changed"
            if changed_at == "cp":
                raise subprocess.CalledProcessError(1, "ollama")

    monkeypatch.setattr(download, "native", native)
    with pytest.raises(ValueError, match="cleanup incomplete"):
        download.pull("tiny")
    assert not any(call[0] == "rm" for call in calls)
    if changed_at == "pull":
        assert not any(call[0] == "cp" for call in calls)


def test_pull_launches_admitted_child_and_exposes_usage(monkeypatch):
    calls = []
    monkeypatch.setattr(models.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess(args, 0))
    result = CliRunner().invoke(models.app, ["pull", "tiny"])
    assert result.exit_code == 0, result.output
    args, kwargs = calls[0]
    assert args[:6] == ["st", "tools", "run", "--label", "Download Ollama model tiny", "--"]
    assert args[-3:] == ["-m", "agent_hub_st.model_download", "tiny"]
    assert "env" not in kwargs
    spec = next(spec for spec in collect_usage_specs(models.app) if spec.surface == "st.models.pull")
    assert spec.on_demand == "model administration"
    assert CliRunner().invoke(models.app, ["pull", "--help"]).exit_code == 0


def test_admission_subprocess_does_not_export_owner_import_path(monkeypatch, tmp_path):
    """A fixture ST core and owner both provide app; only the child uses owner Python."""
    owner = tmp_path / "owner"
    core = tmp_path / "core"
    for root, identity in ((owner, "agent-hub"), (core, "summitflow")):
        package = root / "app"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "config.py").write_text(f"IDENTITY = {identity!r}\n")
    # This represents the extension's in-process import path, never an ST env var.
    monkeypatch.syspath_prepend(str(owner))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    marker = tmp_path / "child-ok"
    st = tmp_path / "st"
    child_code = f"import agent_hub_st.model_download; from pathlib import Path; Path({str(marker)!r}).write_text('ok')"
    st.write_text(
        f"#!{sys.executable} -S\n"  # Fixture core has no owner editable-site hooks.
        "import subprocess, sys\n"
        f"sys.path.append({str(core)!r})\n"
        "from app.config import IDENTITY\n"
        "assert IDENTITY == 'summitflow', IDENTITY\n"
        "assert sys.argv[1:3] == ['tools', 'run']\n"
        "assert sys.argv[-3:] == ['-m', 'agent_hub_st.model_download', 'tiny']\n"
        f"assert sys.argv[-4] == {sys.executable!r}\n"
        f"subprocess.run([sys.argv[-4], '-c', {child_code!r}], check=True)\n"
    )
    st.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    result = CliRunner().invoke(models.app, ["pull", "tiny"])
    assert result.exit_code == 0, result.output
    assert marker.read_text() == "ok"
