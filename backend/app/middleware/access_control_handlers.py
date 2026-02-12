"""Request handlers for access control middleware."""

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.access_control_auth import (
    detect_tool_type,
    get_cached_client,
    verify_client_secret,
)
from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    CLIENT_SECRET_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    TOOL_NAME_HEADER,
)
from app.middleware.access_control_logging import log_rejection, log_request
from app.middleware.access_control_responses import (
    authentication_failed_response,
    client_blocked_response,
    client_suspended_response,
    internal_error_response,
    missing_headers_response,
)


def set_internal_state(request: Request) -> None:
    """Set request state for internal dashboard requests."""
    request.state.client = None
    request.state.client_id = None
    request.state.request_source = "agent-hub-dashboard"
    request.state.is_internal = True


async def handle_auth_bypass(
    request: Request, call_next: Any, path: str, method: str, start_time: float
) -> Response:
    """Handle auth bypass paths (log but don't authenticate)."""
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


async def handle_authenticated_request(
    request: Request, call_next: Any, path: str, method: str, start_time: float
) -> Response:
    """Handle authenticated API requests."""
    # Get auth headers
    client_id = request.headers.get(CLIENT_ID_HEADER)
    client_secret = request.headers.get(CLIENT_SECRET_HEADER)
    request_source = request.headers.get(REQUEST_SOURCE_HEADER)
    source_client = request.headers.get(SOURCE_CLIENT_HEADER)
    tool_name = request.headers.get(TOOL_NAME_HEADER)
    source_path = request.headers.get(SOURCE_PATH_HEADER)
    tool_type = detect_tool_type(source_client)

    # Check required headers
    missing_headers = []
    if not client_id:
        missing_headers.append(CLIENT_ID_HEADER)
    if not client_secret:
        missing_headers.append(CLIENT_SECRET_HEADER)
    if not request_source:
        missing_headers.append(REQUEST_SOURCE_HEADER)

    if missing_headers:
        await log_request(
            client_id=None,
            request_source=request_source,
            endpoint=path,
            method=method,
            status_code=400,
            rejection_reason="missing_required_headers",
            latency_ms=int((time.time() - start_time) * 1000),
            tool_type=tool_type,
            tool_name=tool_name,
            source_path=source_path,
        )
        return missing_headers_response(
            [CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, REQUEST_SOURCE_HEADER]
        )

    # Authenticate client
    try:
        assert client_id is not None and client_secret is not None
        client_data = await get_cached_client(client_id)

        if not client_data:
            await log_rejection(
                path,
                method,
                start_time,
                client_id,
                request_source,
                tool_type,
                tool_name,
                source_path,
                "authentication_failed",
            )
            return authentication_failed_response()

        # Verify secret
        if not verify_client_secret(client_secret, client_data["secret_hash"], client_id):
            await log_rejection(
                path,
                method,
                start_time,
                client_id,
                request_source,
                tool_type,
                tool_name,
                source_path,
                "authentication_failed",
            )
            return authentication_failed_response()

        # Check client status
        if client_data["status"] == "suspended":
            await log_rejection(
                path,
                method,
                start_time,
                client_id,
                request_source,
                tool_type,
                tool_name,
                source_path,
                "client_suspended",
            )
            return client_suspended_response(client_data)

        if client_data["status"] == "blocked":
            await log_rejection(
                path,
                method,
                start_time,
                client_id,
                request_source,
                tool_type,
                tool_name,
                source_path,
                "client_blocked",
            )
            return client_blocked_response(client_data)

        # Attach authenticated client info to request.state
        request.state.client = None  # Only primitive data is cached, not ORM objects
        request.state.client_id = client_data["id"]
        request.state.request_source = request_source
        request.state.is_internal = False

    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
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
        tool_type=tool_type,
        tool_name=tool_name,
        source_path=source_path,
    )

    return response
