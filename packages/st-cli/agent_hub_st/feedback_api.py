"""API client for Agent Hub feedback system."""

from __future__ import annotations

from typing import Any, cast

import httpx
import typer
from st_sdk.config import get_agent_hub_url
from st_sdk.credentials import load_credentials
from st_sdk.output import output_error

from ._http_errors import parse_error_detail, raise_connect_error, raise_timeout_error


def _dispatch_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None,
    json: dict[str, Any] | None,
    headers: dict[str, str],
) -> httpx.Response:
    """Dispatch an HTTP request using the given client."""
    if method == "GET":
        return client.get(url, params=params, headers=headers)
    if method == "PATCH":
        return client.patch(url, json=json, headers=headers)
    if method == "DELETE":
        return client.delete(url, headers=headers)
    return client.post(url, json=json, headers=headers)


def feedback_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to Agent Hub feedback API with proper authentication."""
    client_id, request_source = load_credentials(default_source="st-feedback")

    headers = {
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
        "X-Source-Client": "st-cli",
        "X-Tool-Name": "st feedback",
    }

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = _dispatch_request(
                client, method, url, params=params, json=json, headers=headers
            )

        if response.status_code >= 400:
            detail = parse_error_detail(response)
            output_error(f"{detail}")
            raise typer.Exit(1) from None

        return cast(dict[str, Any], response.json())
    except httpx.ConnectError as e:
        return raise_connect_error("Agent Hub", agent_hub_url, e)
    except httpx.TimeoutException as e:
        return raise_timeout_error("Agent Hub", agent_hub_url, 30.0, e)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None
