"""The managed relay preserves native bytes without exposing upstream URLs."""

from __future__ import annotations

import hashlib
import json
import subprocess
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
    monkeypatch.setattr(download, "installed_models", lambda endpoint: {})
    calls = []
    digests = iter([None, None, "wrong" if failure == "verify" else DIGEST])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))

    def native(endpoint, *args, **kwargs):
        calls.append(args)
        if args[0] == failure:
            raise subprocess.CalledProcessError(1, "ollama")
        if failure == "cancel" and args[0] == "pull":
            raise KeyboardInterrupt

    monkeypatch.setattr(download, "native", native)
    if failure:
        with pytest.raises((subprocess.CalledProcessError, KeyboardInterrupt, ValueError)):
            download.pull("tiny")
    else:
        download.pull("tiny")
        assert calls[1] == ("cp", "127.0.0.1:12345/library/tiny:latest", "tiny")
    assert calls[0] == ("pull", "--insecure", "127.0.0.1:12345/library/tiny:latest")
    assert calls[-1] == ("rm", "127.0.0.1:12345/library/tiny:latest")
    assert reg.closed and reg.stopped


def test_existing_destination_is_never_overwritten(monkeypatch):
    reg = FakeRegistry()
    monkeypatch.setattr(download, "Registry", lambda *args: reg)
    monkeypatch.setattr(download, "installed_digest", lambda *args: "existing")
    monkeypatch.setattr(download, "native", lambda *args, **kwargs: pytest.fail("native mutation"))
    with pytest.raises(ValueError, match="already contains"):
        download.pull("tiny")
    assert reg.closed


@pytest.mark.parametrize("collision", ["destination", "temporary"])
def test_concurrent_destination_and_stale_temporary_alias_are_preserved(monkeypatch, collision):
    reg = FakeRegistry()
    monkeypatch.setattr(download, "Registry", lambda *args: reg)
    digests = iter([None, "appeared"])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))
    temporary = "127.0.0.1:12345/library/tiny:latest"
    monkeypatch.setattr(download, "installed_models", lambda endpoint: {temporary: DIGEST} if collision == "temporary" else {})
    calls = []
    monkeypatch.setattr(download, "native", lambda endpoint, *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="leaving it unchanged"):
        download.pull("tiny")
    assert not any(call[0] == "cp" for call in calls)
    assert calls == [] if collision == "temporary" else calls[-1] == ("rm", temporary)
    assert reg.closed and reg.stopped


def test_cleanup_failure_is_reported_as_failure(monkeypatch):
    monkeypatch.setattr(download, "Registry", lambda *args: FakeRegistry())
    monkeypatch.setattr(download, "installed_models", lambda endpoint: {})
    digests = iter([None, None, DIGEST])
    monkeypatch.setattr(download, "installed_digest", lambda *args: next(digests))

    def native(endpoint, *args, **kwargs):
        if args[0] == "rm":
            raise subprocess.CalledProcessError(1, "ollama")

    monkeypatch.setattr(download, "native", native)
    with pytest.raises(ValueError, match="Could not remove temporary model"):
        download.pull("tiny")


def test_pull_launches_admitted_child_and_exposes_usage(monkeypatch):
    calls = []
    monkeypatch.setattr(models.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess(args, 0))
    result = CliRunner().invoke(models.app, ["pull", "tiny"])
    assert result.exit_code == 0, result.output
    args, kwargs = calls[0]
    assert args[:6] == ["st", "tools", "run", "--label", "Download Ollama model tiny", "--"]
    assert args[-3:] == ["-m", "agent_hub_st.model_download", "tiny"]
    assert "PYTHONPATH" in kwargs["env"]
    spec = next(spec for spec in collect_usage_specs(models.app) if spec.surface == "st.models.pull")
    assert spec.on_demand == "model administration"
    assert CliRunner().invoke(models.app, ["pull", "--help"]).exit_code == 0
