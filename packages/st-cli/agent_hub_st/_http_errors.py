"""Shared HTTP transport error helpers for CLI commands."""

from __future__ import annotations

from typing import NoReturn

import httpx
import typer
from st_sdk.output import output_error


def parse_error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error detail from a failed HTTP response.

    Shared across CLI commands to avoid duplicating this pattern.
    """
    try:
        body = response.json()
        return body.get("detail") or body.get("message") or response.text
    except Exception:
        return response.text


def _extract_root_error_message(error: BaseException) -> str:
    """Return the deepest useful exception message."""
    current: BaseException = error
    seen: set[int] = set()

    while id(current) not in seen:
        seen.add(id(current))
        nested = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if nested is None:
            break
        current = nested

    message = str(current).strip()
    return message or current.__class__.__name__


def raise_connect_error(service_name: str, url: str, error: httpx.ConnectError) -> NoReturn:
    """Emit a detailed connect error and exit."""
    detail = _extract_root_error_message(error)
    output_error(f"Cannot connect to {service_name} at {url}: {detail}")
    output_error("Verify the service URL/protocol and that it is reachable from this shell.")
    raise typer.Exit(1) from None


def raise_timeout_error(service_name: str, url: str, timeout: float, error: httpx.TimeoutException) -> NoReturn:
    """Emit a detailed timeout error and exit."""
    detail = _extract_root_error_message(error)
    output_error(f"Request to {service_name} at {url} timed out after {timeout:.0f}s: {detail}")
    output_error("Verify the service is healthy or retry with a larger timeout if the operation is expected to be slow.")
    raise typer.Exit(1) from None
