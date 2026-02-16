"""Access control middleware for mandatory client authentication.

Replaces the kill switch with cryptographic verification:
- X-Client-Id: UUID of registered client
- X-Client-Secret: bcrypt-verified secret (ahc_...)
- X-Request-Source: Caller identification for attribution

All API requests must be authenticated. Internal dashboard uses X-Agent-Hub-Internal bypass.
"""

import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.middleware.access_control_auth import invalidate_client_cache
from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    CLIENT_SECRET_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    TOOL_NAME_HEADER,
)
from app.middleware.access_control_handlers import (
    handle_auth_bypass,
    handle_authenticated_request,
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
    """Middleware for mandatory client authentication.

    All /api/* requests must provide:
    - X-Client-Id: Registered client UUID
    - X-Client-Secret: Valid secret for that client
    - X-Request-Source: Identifier for caller attribution

    Internal dashboard requests bypass auth with X-Agent-Hub-Internal header.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Validate authentication before processing request."""
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

        # Auth bypass paths: skip auth verification but still log requests
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
            logger.debug(f"Internal request bypassing auth: {path}")
            set_internal_state(request)
            return await call_next(request)

        # Perform full authentication
        return await handle_authenticated_request(request, call_next, path, method, start_time)


# Re-export for backward compatibility
__all__ = [
    "CLIENT_ID_HEADER",
    "CLIENT_SECRET_HEADER",
    "REQUEST_SOURCE_HEADER",
    "SOURCE_CLIENT_HEADER",
    "SOURCE_PATH_HEADER",
    "TOOL_NAME_HEADER",
    "AccessControlMiddleware",
    "invalidate_client_cache",
]
