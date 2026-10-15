"""Refuse requests from other sites before any routing or auth.

The backend listens on loopback only, but any page in the owner's browser can still reach it:
- DNS rebinding: a public name re-pointed at 127.0.0.1 makes its page same-origin with us, so
  only the Host header (still ``evil.example``) tells it apart. Host must be a trusted name.
- Cross-site writes: a visited page can send a no-preflight POST (bodyless or text/plain) or open
  a WebSocket. Unsafe methods and WebSocket handshakes that carry an Origin must use one of our
  CORS origins. Clients that send no Origin (agents, CLIs, services) are unaffected.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(authority: str) -> str | None:
    try:
        return urlsplit(f"//{authority}").hostname
    except ValueError:
        return None


class RequestOriginMiddleware:
    """400 for an untrusted Host, 403 for a foreign Origin on a write or WebSocket handshake."""

    def __init__(self, app: ASGIApp, *, trusted_hosts: Iterable[str], allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.trusted_hosts = frozenset(host.strip("[]").lower() for host in trusted_hosts)
        self.allowed_origins = frozenset(origin.rstrip("/") for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        if _hostname(headers.get("host", "")) not in self.trusted_hosts:
            await self._refuse(scope, receive, send, 400, "host_not_allowed")
            return
        origin = headers.get("origin")
        unsafe = scope["type"] == "websocket" or scope["method"] not in _SAFE_METHODS
        if unsafe and origin is not None and origin not in self.allowed_origins:
            await self._refuse(scope, receive, send, 403, "origin_not_allowed")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, error: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008, "reason": error})
            return
        body = json.dumps({"error": error}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
