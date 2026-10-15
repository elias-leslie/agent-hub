"""Request handlers for access control middleware."""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.core.request_actor import bind_request_actor
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

# Session heartbeats fire every few seconds per live session and carried most of
# request_logs volume. Successful ones are not logged; failures still are.
_HEARTBEAT_PATH_RE = re.compile(r"^/api/(?:session-ingestion/)?sessions/[^/]+/heartbeat/?$")


def should_log_request(path: str, status_code: int) -> bool:
    """Return False for successful session heartbeats, True otherwise."""
    return not (200 <= status_code < 300 and _HEARTBEAT_PATH_RE.match(path))


def request_session_id(request: Request) -> str | None:
    """Session attributed to a request: handler-set state, else the path param."""
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        return str(session_id)
    path_session_id = request.path_params.get("session_id")
    return str(path_session_id) if path_session_id else None


def set_internal_state(request: Request) -> None:
    """Set request state for internal dashboard requests."""
    request.state.client = None
    request.state.client_id = None
    request.state.allowed_projects = None  # Internal = unrestricted
    request.state.request_source = "agent-hub-dashboard"
    request.state.is_internal = True
    bind_request_actor(
        client_id=request.headers.get(CLIENT_ID_HEADER),
        request_source=request.headers.get(REQUEST_SOURCE_HEADER) or "agent-hub-dashboard",
        internal=True,
    )


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
    bind_request_actor(client_id=client_id, request_source=request.state.request_source, internal=False)

    # Process request
    response: Response = await call_next(request)

    # Log request
    if not should_log_request(path, response.status_code):
        return response
    latency_ms = int((time.time() - start_time) * 1000)
    await log_request(
        client_id=client_id,
        request_source=request_source,
        endpoint=path,
        method=method,
        status_code=response.status_code,
        rejection_reason=None,
        latency_ms=latency_ms,
        session_id=request_session_id(request),
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

    if not should_log_request(path, response.status_code):
        return response

    async def _log_identified() -> None:
        await log_request(
            client_id=client_id,
            request_source=request_source,
            endpoint=path,
            method=method,
            status_code=response.status_code,
            rejection_reason=None,
            latency_ms=int((time.time() - start_time) * 1000),
            model=getattr(request.state, "resolved_model", None),
            session_id=request_session_id(request),
            agent_slug=getattr(request.state, "agent_slug", None),
            tool_type=headers["tool_type"],
            tool_name=headers["tool_name"],
            source_path=headers["source_path"],
            timed_out=getattr(request.state, "timed_out", False),
            used_fallback=getattr(request.state, "used_fallback", False),
            fallback_model=getattr(request.state, "fallback_model", None),
        )

    if is_event_stream(response) and hasattr(response, "body_iterator"):
        # call_next returns once headers are ready; logging now would record
        # time-to-first-byte. Log on stream end so latency_ms is total latency,
        # matching non-streaming rows in dashboard model-call metrics.
        response.body_iterator = _log_on_stream_end(response.body_iterator, _log_identified)
        return response

    await _log_identified()
    return response


def is_event_stream(response: Response) -> bool:
    """True for SSE responses, whose body streams after call_next returns."""
    return response.headers.get("content-type", "").startswith("text/event-stream")


# Strong references so stream-end log tasks are not garbage-collected mid-flight.
_stream_log_tasks: set[asyncio.Task[None]] = set()


async def _log_on_stream_end(
    body: AsyncIterator[Any], write_log: Callable[[], Awaitable[None]]
) -> AsyncIterator[Any]:
    """Pass the stream through and write its request log once it ends.

    The write is scheduled as a task so it also happens when the client
    disconnects and the stream is cancelled (no await is possible then).
    """
    try:
        async for chunk in body:
            yield chunk
    finally:
        task = asyncio.create_task(write_log())
        _stream_log_tasks.add(task)
        task.add_done_callback(_stream_log_tasks.discard)
