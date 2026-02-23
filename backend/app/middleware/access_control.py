"""Access control middleware for client identification and attribution.

Lightweight client identification — no secret verification.
Agent Hub binds to localhost only; the primary gate is per-project cost budgets.

- X-Client-Id: UUID of registered client (for attribution + rate limiting)
- X-Request-Source: Caller identification for telemetry

All API requests must be identified. Internal dashboard uses X-Agent-Hub-Internal bypass.
"""

import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.middleware.access_control_auth import invalidate_client_cache
from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    TOOL_NAME_HEADER,
)
from app.middleware.access_control_handlers import (
    handle_auth_bypass,
    handle_identified_request,
    set_internal_state,
)
from app.middleware.access_control_paths import (
    is_auth_bypass_path,
    is_internal_only_path,
    is_internal_request,
    is_path_exempt,
)
from app.middleware.access_control_responses import internal_only_response

logger = logging.getLogger(__name__)



class AccessControlMiddleware(BaseHTTPMiddleware):
    """Middleware for client identification and attribution.

    All /api/* requests must provide:
    - X-Client-Id: Registered client UUID (for rate limiting + attribution)
    - X-Request-Source: Identifier for caller attribution

    Internal dashboard requests bypass identification with X-Agent-Hub-Internal header.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Identify client before processing request."""
        path = request.url.path
        method = request.method
        start_time = time.time()

        # Pass through CORS preflight requests to the CORS middleware
        if method == "OPTIONS":
            return await call_next(request)

        # Skip non-API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip exempt paths (truly public: health checks, docs, webhooks, websocket)
        if is_path_exempt(path):
            return await call_next(request)

        # Auth bypass paths: skip identification but still log requests
        if is_auth_bypass_path(path):
            return await handle_auth_bypass(request, call_next, path, method, start_time)

        # Check internal-only paths (dashboard endpoints that require internal header)
        if is_internal_only_path(path):
            if is_internal_request(request):
                logger.debug(f"Internal request to dashboard endpoint: {path}")
                set_internal_state(request)
                return await call_next(request)
            else:
                return internal_only_response()

        # Skip internal agent-hub dashboard calls (for non-internal-only paths)
        if is_internal_request(request):
            logger.debug(f"Internal request bypassing identification: {path}")
            set_internal_state(request)
            return await call_next(request)

        # Perform client identification
        return await handle_identified_request(request, call_next, path, method, start_time)


__all__ = [
    "CLIENT_ID_HEADER",
    "REQUEST_SOURCE_HEADER",
    "SOURCE_CLIENT_HEADER",
    "SOURCE_PATH_HEADER",
    "TOOL_NAME_HEADER",
    "AccessControlMiddleware",
    "invalidate_client_cache",
]
