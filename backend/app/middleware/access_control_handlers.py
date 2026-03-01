"""Request handlers for access control middleware."""

import logging
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.access_control_auth import detect_tool_type
from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    TOOL_NAME_HEADER,
)
from app.middleware.access_control_handler_helpers import (
    extract_request_headers,
    handle_missing_headers,
    identify_client,
    set_identified_state,
)
from app.middleware.access_control_logging import log_request
from app.middleware.access_control_responses import internal_error_response

logger = logging.getLogger(__name__)


def set_internal_state(request: Request) -> None:
    """Set request state for internal dashboard requests."""
    request.state.client = None
    request.state.client_id = None
    request.state.allowed_projects = None  # Internal = unrestricted
    request.state.request_source = "agent-hub-dashboard"
    request.state.is_internal = True


async def handle_auth_bypass(
    request: Request, call_next: Any, path: str, method: str, start_time: float
) -> Response:
    """Handle auth bypass paths (log but don't identify)."""
    # Extract headers for logging (no validation, just attribution)
    client_id = request.headers.get(CLIENT_ID_HEADER)
    source_client = request.headers.get(SOURCE_CLIENT_HEADER)
    tool_name = request.headers.get(TOOL_NAME_HEADER)
    source_path = request.headers.get(SOURCE_PATH_HEADER)
    request_source = request.headers.get(REQUEST_SOURCE_HEADER)
    tool_type = detect_tool_type(source_client)

    # Set request state (no client validation)
    request.state.client = None
    request.state.client_id = client_id
    request.state.allowed_projects = None  # Auth-bypass paths have no project scoping
    request.state.request_source = request_source or "auth-bypass"
    request.state.is_internal = False

    # Process request
    response: Response = await call_next(request)

    # Log request
    latency_ms = int((time.time() - start_time) * 1000)
    await log_request(
        client_id=client_id,
        request_source=request_source,
        endpoint=path,
        method=method,
        status_code=response.status_code,
        rejection_reason=None,
        latency_ms=latency_ms,
        tool_type=tool_type,
        tool_name=tool_name,
        source_path=source_path,
    )
    return response


async def handle_identified_request(
    request: Request, call_next: Any, path: str, method: str, start_time: float
) -> Response:
    """Handle identified API requests (client lookup by ID, no secret verification)."""
    headers = extract_request_headers(request)
    client_id = headers["client_id"]
    request_source = headers["request_source"]

    # Check required headers (client_id + request_source)
    if not client_id or not request_source:
        return await handle_missing_headers(headers, path, method, start_time)

    # Identify client (lookup + status check)
    try:
        client_data, error_response = await identify_client(
            headers, path, method, start_time
        )
        if error_response is not None:
            return error_response

        assert client_data is not None
        set_identified_state(request, client_data, request_source)

    except Exception as e:
        logger.error(f"Access control check failed: {e}")
        return internal_error_response()

    # Process request
    response: Response = await call_next(request)

    # Log successful request
    latency_ms = int((time.time() - start_time) * 1000)
    agent_slug = getattr(request.state, "agent_slug", None)
    await log_request(
        client_id=client_id,
        request_source=request_source,
        endpoint=path,
        method=method,
        status_code=response.status_code,
        rejection_reason=None,
        latency_ms=latency_ms,
        agent_slug=agent_slug,
        tool_type=headers["tool_type"],
        tool_name=headers["tool_name"],
        source_path=headers["source_path"],
        timed_out=getattr(request.state, "timed_out", False),
        used_fallback=getattr(request.state, "used_fallback", False),
        fallback_model=getattr(request.state, "fallback_model", None),
    )

    return response
