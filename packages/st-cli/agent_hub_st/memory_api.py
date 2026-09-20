"""API client for Agent Hub memory system."""

from __future__ import annotations

import json as jsonlib
import time
from typing import Any, cast

import httpx
import typer
from st_sdk.config import get_agent_hub_url
from st_sdk.credentials import load_credentials
from st_sdk.output import output_error

from ._http_errors import raise_connect_error, raise_timeout_error

_HTTP_TIMEOUT_READ = 90.0
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_DEFAULT_RETRY_MAX_BACKOFF_SECONDS = 1.0


def _dispatch(client: httpx.Client, method: str, url: str, **kw: Any) -> httpx.Response:
    """Dispatch HTTP request by method."""
    if method == "GET":
        return client.get(url, params=kw.get("params"), headers=kw["headers"])
    if method == "DELETE":
        return client.delete(url, params=kw.get("params"), headers=kw["headers"])
    if method == "PUT":
        return client.put(url, json=kw.get("json"), headers=kw["headers"])
    if method == "PATCH":
        return client.patch(url, json=kw.get("json"), headers=kw["headers"])
    return client.post(url, json=kw.get("json"), headers=kw["headers"])


def _format_error_payload(payload: dict[str, Any], fallback: str) -> str:
    """Render Agent Hub error payloads into a concise CLI message."""
    message = str(payload.get("message") or payload.get("detail") or payload.get("error") or fallback)
    parts = [message]

    details = payload.get("details")
    if details:
        if isinstance(details, list):
            rendered = ", ".join(
                item.get("message") if isinstance(item, dict) and item.get("message") else jsonlib.dumps(item, ensure_ascii=True)
                for item in details
            )
        elif isinstance(details, dict):
            rendered = str(details.get("message") or jsonlib.dumps(details, ensure_ascii=True))
        else:
            rendered = str(details)
        if rendered and rendered not in message:
            parts.append(rendered)

    hint = payload.get("hint")
    if hint:
        parts.append(str(hint))

    return " | ".join(parts)


def _check_response(response: httpx.Response, agent_hub_url: str) -> dict[str, Any]:
    """Validate response and return parsed body."""
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            detail = response.text
        else:
            detail = _format_error_payload(payload if isinstance(payload, dict) else {}, response.text)
        output_error(f"API error ({response.status_code}): {detail}")
        raise typer.Exit(1) from None
    if response.status_code == 204:
        return {"success": True}
    return cast(dict[str, Any], response.json())


def _sleep_backoff(attempt: int) -> None:
    delay = min(
        _DEFAULT_RETRY_BACKOFF_SECONDS * (2 ** max(attempt - 1, 0)),
        _DEFAULT_RETRY_MAX_BACKOFF_SECONDS,
    )
    time.sleep(delay)


def agent_hub_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    scope: str = "global",
    scope_id: str | None = None,
    tool_name: str = "st memory",
    retries: int = 1,
    read_timeout_seconds: float = _HTTP_TIMEOUT_READ,
) -> dict[str, Any]:
    """Make a request to Agent Hub API with proper authentication."""
    client_id, request_source = load_credentials(default_source="st-memory")
    headers = {
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
        "X-Source-Client": "st-cli",
        "X-Tool-Name": tool_name,
    }
    if scope != "global":
        headers["X-Memory-Scope"] = scope
    if scope_id:
        headers["X-Scope-Id"] = scope_id

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{path}"
    # Graphiti embedding + Neo4j writes can take 30-60s; generous timeout prevents partial ops.
    timeout = httpx.Timeout(connect=5.0, read=read_timeout_seconds, write=30.0, pool=30.0)
    attempts = max(retries, 1)
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = _dispatch(client, method, url, params=params, json=json, headers=headers)
                return _check_response(response, agent_hub_url)
        except typer.Exit:
            raise
        except httpx.ConnectError as e:
            if attempt >= attempts:
                raise_connect_error("Agent Hub", agent_hub_url, e)
            _sleep_backoff(attempt)
        except httpx.TimeoutException as e:
            if attempt >= attempts:
                raise_timeout_error("Agent Hub", agent_hub_url, _HTTP_TIMEOUT_READ, e)
            _sleep_backoff(attempt)
        except Exception as e:
            if attempt >= attempts:
                output_error(f"Request failed: {e}")
                raise typer.Exit(1) from None
            _sleep_backoff(attempt)
    raise typer.Exit(1)
