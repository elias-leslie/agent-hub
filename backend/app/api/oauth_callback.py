"""Temporary HTTP callback server for receiving OAuth redirects."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, urlparse

from app.api.oauth_schemas import _ERROR_HTML, _SUCCESS_HTML
from app.api.oauth_store import register_server, unregister_server

logger = logging.getLogger(__name__)


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    path: str,
    provider: str,
    on_callback: asyncio.Future[tuple[str, str]],
) -> None:
    """Handle a single HTTP connection to the callback server."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=30)
        request_str = request_line.decode("utf-8", errors="replace").strip()

        parts = request_str.split(" ")
        if len(parts) < 2:
            writer.close()
            return

        url = urlparse(parts[1])
        params = parse_qs(url.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        html = _build_response_html(url.path, path, provider, code, state, error, on_callback)
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(html.encode())}\r\n"
            f"Connection: close\r\n\r\n"
            f"{html}"
        )
        writer.write(response.encode())
        await writer.drain()
    except Exception as e:
        logger.warning("Callback handler error: %s", e)
    finally:
        writer.close()


def _build_response_html(
    url_path: str,
    expected_path: str,
    provider: str,
    code: str | None,
    state: str | None,
    error: str | None,
    on_callback: asyncio.Future[tuple[str, str]],
) -> str:
    """Resolve the callback future and return the HTML response to send."""
    if url_path == expected_path and code and state:
        if not on_callback.done():
            on_callback.set_result((code, state))
        return _SUCCESS_HTML.format(provider=provider)

    if error:
        err_desc = error
        if not on_callback.done():
            on_callback.set_exception(RuntimeError(f"OAuth error: {err_desc}"))
        return _ERROR_HTML.format(provider=provider, error=err_desc)

    return _ERROR_HTML.format(provider=provider, error="Missing code or state parameter")


async def start_callback_server(
    port: int,
    path: str,
    provider: str,
    on_callback: asyncio.Future[tuple[str, str]],
) -> asyncio.Server | None:
    """Start a temporary HTTP server to receive the OAuth callback.

    Returns the server instance, or None if the port is already in use.
    """
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_connection(reader, writer, path, provider, on_callback)

    try:
        server = await asyncio.start_server(handle, "127.0.0.1", port)
        return server
    except OSError as e:
        logger.warning("Cannot start callback server on port %d: %s", port, e)
        return None


async def run_callback_flow(
    port: int,
    path: str,
    provider: str,
    timeout: float = 300,
) -> tuple[str, str]:
    """Start callback server, wait for callback, return (code, state).

    Raises RuntimeError if port is in use, TimeoutError if no callback received.
    """
    loop = asyncio.get_running_loop()
    callback_future: asyncio.Future[tuple[str, str]] = loop.create_future()

    server = await start_callback_server(port, path, provider, callback_future)
    if server is None:
        raise RuntimeError(f"Port {port} is already in use")

    register_server(provider, server)
    try:
        code, state = await asyncio.wait_for(callback_future, timeout=timeout)
        return code, state
    except TimeoutError:
        raise TimeoutError(f"OAuth callback timed out after {timeout}s") from None
    finally:
        server.close()
        await server.wait_closed()
        unregister_server(provider)
