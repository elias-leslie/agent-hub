"""Helper functions for access_control_handlers.py.

Extracted to keep access_control_handlers.py under 150 lines.
"""

import logging
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.access_control_auth import (
    detect_tool_type,
    get_cached_client,
)
from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    TOOL_NAME_HEADER,
)
from app.middleware.access_control_logging import log_rejection, log_request
from app.middleware.access_control_responses import (
    client_blocked_response,
    client_not_found_response,
    client_suspended_response,
    missing_headers_response,
)

logger = logging.getLogger(__name__)


def extract_request_headers(request: Request) -> dict[str, Any]:
    """Extract all relevant identification/attribution headers from request."""
    source_client = request.headers.get(SOURCE_CLIENT_HEADER)
    return {
        "client_id": request.headers.get(CLIENT_ID_HEADER),
        "request_source": request.headers.get(REQUEST_SOURCE_HEADER),
        "source_client": source_client,
        "tool_name": request.headers.get(TOOL_NAME_HEADER),
        "source_path": request.headers.get(SOURCE_PATH_HEADER),
        "tool_type": detect_tool_type(source_client),
    }


async def handle_missing_headers(
    headers: dict[str, Any],
    path: str,
    method: str,
    start_time: float,
) -> Response:
    """Log and return response for missing required headers."""
    await log_request(
        client_id=None,
        request_source=headers["request_source"],
        endpoint=path,
        method=method,
        status_code=400,
        rejection_reason="missing_required_headers",
        latency_ms=int((time.time() - start_time) * 1000),
        tool_type=headers["tool_type"],
        tool_name=headers["tool_name"],
        source_path=headers["source_path"],
    )
    return missing_headers_response(
        [CLIENT_ID_HEADER, REQUEST_SOURCE_HEADER]
    )


async def _check_client_status(
    client_data: dict[str, Any],
    path: str, method: str, start_time: float,
    client_id: str, request_source: str | None,
    tool_type: str, tool_name: str | None, source_path: str | None,
) -> Response | None:
    """Check client status (suspended/blocked). Returns error response or None."""
    status = client_data["status"]
    if status == "suspended":
        await log_rejection(
            path, method, start_time, client_id,
            request_source, tool_type, tool_name, source_path,
            "client_suspended",
        )
        return client_suspended_response(client_data)
    if status == "blocked":
        await log_rejection(
            path, method, start_time, client_id,
            request_source, tool_type, tool_name, source_path,
            "client_blocked",
        )
        return client_blocked_response(client_data)
    return None


async def identify_client(
    headers: dict[str, Any],
    path: str,
    method: str,
    start_time: float,
) -> tuple[dict[str, Any] | None, Response | None]:
    """Identify client by ID and check status. No secret verification.

    Returns (client_data, None) on success, or (None, error_response) on failure.
    """
    client_id: str = headers["client_id"]
    request_source = headers["request_source"]
    tool_type = headers["tool_type"]
    tool_name = headers["tool_name"]
    source_path = headers["source_path"]
    rejection_args = (path, method, start_time, client_id, request_source, tool_type, tool_name, source_path)

    client_data = await get_cached_client(client_id)
    if not client_data:
        await log_rejection(*rejection_args, "client_not_found")
        return None, client_not_found_response()

    status_error = await _check_client_status(client_data, *rejection_args)
    if status_error is not None:
        return None, status_error

    return client_data, None


def set_identified_state(request: Request, client_data: dict[str, Any], request_source: str | None) -> None:
    """Attach identified client info to request.state."""
    request.state.client = None  # Only primitive data is cached, not ORM objects
    request.state.client_id = client_data["id"]
    request.state.allowed_projects = client_data.get("allowed_projects")
    request.state.request_source = request_source
    request.state.is_internal = False
