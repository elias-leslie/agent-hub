"""One frozen public manifest, exposed briefly as a loopback OCI registry."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
RANGE = re.compile(r"bytes=(?:[0-9]+-[0-9]*|-[0-9]+)\Z")
COMPONENT = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
MODEL = re.compile(rf"(?:(?P<namespace>{COMPONENT})/)?(?P<name>{COMPONENT})(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]*))?\Z")


def model_name(value: str) -> tuple[str, str]:
    match = MODEL.fullmatch(value)
    if not match:
        raise ValueError("Use a public Ollama model name: [namespace/]name[:tag].")
    return f"{match['namespace'] or 'library'}/{match['name']}", match['tag'] or "latest"


class Registry:
    def __init__(self, model: str, base: str) -> None:
        self.repository, self.tag = model_name(model)
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("ST_MODELS_REGISTRY must be an HTTPS registry origin.")
        self.base = base.rstrip("/")
        self.manifest_path = f"/v2/{self.repository}/manifests/{self.tag}"
        self.client = httpx.Client(trust_env=False, timeout=60)
        try:
            with self.upstream(self.manifest_path) as response:
                response.raise_for_status()
                self.manifest = response.read()
                self.media_type = response.headers.get("Content-Type", "application/vnd.docker.distribution.manifest.v2+json")
            manifest = json.loads(self.manifest)
            descriptors = [manifest["config"], *manifest["layers"]]
            self.blobs = {item["digest"] for item in descriptors}
            if not self.blobs or any(not DIGEST.fullmatch(digest) for digest in self.blobs):
                raise ValueError("Registry manifest contains unsupported blob digests.")
            self.digest = "sha256:" + hashlib.sha256(self.manifest).hexdigest()
        except BaseException:
            self.client.close()
            raise

    @contextmanager
    def upstream(self, path: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> Iterator[httpx.Response]:
        url = self.base + path
        for _ in range(6):
            # Fresh requests never forward authentication, cookies, or registry challenges.
            request = httpx.Request(method, url, headers={"Accept-Encoding": "identity", **(headers or {})})
            response = self.client.send(request, stream=True)
            if not response.is_redirect:
                try:
                    yield response
                finally:
                    response.close()
                return
            target = response.next_request.url if response.next_request else None
            response.close()
            if target is None or target.scheme != "https" or target.userinfo:
                raise ValueError("Registry returned an unsupported redirect.")
            url = str(target)
        raise ValueError("Registry returned too many redirects.")

    @contextmanager
    def serve(self) -> Iterator[str]:
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def do_HEAD(self) -> None:
                self.relay()

            def do_GET(self) -> None:
                self.relay()

            def relay(self) -> None:
                if self.path == "/v2/":
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == registry.manifest_path:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(registry.manifest)))
                    self.send_header("Content-Type", registry.media_type)
                    self.send_header("Docker-Content-Digest", registry.digest)
                    self.end_headers()
                    if self.command == "GET":
                        self.wfile.write(registry.manifest)
                    return
                prefix = f"/v2/{registry.repository}/blobs/"
                if not self.path.startswith(prefix) or self.path[len(prefix):] not in registry.blobs:
                    self.send_error(404)
                    return
                headers = {}
                if value := self.headers.get("Range"):
                    if not RANGE.fullmatch(value):
                        self.send_error(416)
                        return
                    headers["Range"] = value
                started = False
                try:
                    with registry.upstream(self.path, method=self.command, headers=headers) as response:
                        if response.status_code not in (200, 206, 416):
                            self.send_error(502, "Public registry download failed")
                            return
                        self.send_response(response.status_code)
                        # Ollama 0.30.5 asks Response.Location even for a 200 blob response.
                        self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}{self.path}")
                        for name in ("Content-Length", "Content-Range", "Content-Type", "Accept-Ranges"):
                            if value := response.headers.get(name):
                                self.send_header(name, value)
                        self.end_headers()
                        started = True
                        if self.command == "GET":
                            for chunk in response.iter_raw():
                                self.wfile.write(chunk)
                except (httpx.HTTPError, httpx.InvalidURL, ValueError, OSError):
                    if not started:
                        self.send_error(502, "Public registry download failed")
                    self.close_connection = True

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"127.0.0.1:{server.server_port}/{self.repository}:{self.tag}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def close(self) -> None:
        self.client.close()
