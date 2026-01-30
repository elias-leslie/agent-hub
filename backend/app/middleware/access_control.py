"""Access control middleware for mandatory client authentication.

Replaces the kill switch with cryptographic verification:
- X-Client-Id: UUID of registered client
- X-Client-Secret: bcrypt-verified secret (ahc_...)
- X-Request-Source: Caller identification for attribution

All API requests must be authenticated. Internal dashboard uses X-Agent-Hub-Internal bypass.
"""

import logging
import time
from time import monotonic
from typing import Any

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.db import get_db
from app.models import Client, RequestLog
from app.services.client_auth import verify_secret

# Client lookup cache: client_id -> (Client data dict, timestamp)
_client_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CLIENT_CACHE_TTL = 600  # 10 minutes (internal service-to-service)


async def _get_cached_client(client_id: str) -> dict[str, Any] | None:
    """Get client from cache or database.

    Returns dict with: id, secret_hash, status, display_name, suspension_reason, suspended_at
    """
    now = monotonic()

    if client_id in _client_cache:
        data, timestamp = _client_cache[client_id]
        if now - timestamp < _CLIENT_CACHE_TTL:
            return data
        del _client_cache[client_id]

    async for db in get_db():
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            return None

        data = {
            "id": str(client.id),
            "secret_hash": client.secret_hash,
            "status": client.status,
            "display_name": client.display_name,
            "suspension_reason": client.suspension_reason,
            "suspended_at": client.suspended_at,
            "_client_obj": client,
        }
        _client_cache[client_id] = (data, now)
        return data

    return None


def invalidate_client_cache(client_id: str) -> None:
    """Invalidate cached client data (call after status changes)."""
    _client_cache.pop(client_id, None)


logger = logging.getLogger(__name__)

# Required headers for authentication
CLIENT_ID_HEADER = "X-Client-Id"
CLIENT_SECRET_HEADER = "X-Client-Secret"
REQUEST_SOURCE_HEADER = "X-Request-Source"
SOURCE_CLIENT_HEADER = "X-Source-Client"  # Identifies client type (st-cli, sdk, etc.)
TOOL_NAME_HEADER = "X-Tool-Name"  # Specific command/method (e.g., "st complete", "client.complete")
SOURCE_PATH_HEADER = "X-Source-Path"  # Caller file path for debugging

# Internal service header for agent-hub dashboard self-calls
INTERNAL_SERVICE_HEADER = "X-Agent-Hub-Internal"


def detect_tool_type(source_client: str | None) -> str:
    """Detect tool type from X-Source-Client header.

    Returns:
        'cli' if source indicates CLI (e.g., 'st-cli')
        'sdk' if source indicates SDK (e.g., 'agent-hub-sdk')
        'api' otherwise (default)
    """
    if not source_client:
        return "api"
    source_lower = source_client.lower()
    if "cli" in source_lower:
        return "cli"
    if "sdk" in source_lower:
        return "sdk"
    return "api"


# Endpoints exempt from authentication (health, docs, static)
EXEMPT_PATHS = frozenset(
    [
        "/",
        "/health",
        "/status",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/health",
        "/api/status",
        "/favicon.ico",
    ]
)

# Path prefixes exempt from authentication
# MINIMAL: Only truly public endpoints or special auth (WebSocket, webhooks)
EXEMPT_PREFIXES = (
    "/ws/",  # WebSocket connections (uses different auth model)
    "/api/webhooks",  # Webhook delivery (uses signature verification)
)

# Path prefixes that require INTERNAL header (dashboard-only, not public)
# These bypass full auth but require X-Agent-Hub-Internal header
INTERNAL_ONLY_PREFIXES = (
    "/api/admin",  # Admin dashboard endpoints
    "/api/access-control",  # Access control management
    "/api/settings",  # Settings management
    "/api/global-instructions",  # Global instructions (frontend dashboard)
)


def is_path_exempt(path: str) -> bool:
    """Check if path is exempt from authentication."""
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def is_internal_only_path(path: str) -> bool:
    """Check if path requires internal header (dashboard-only endpoints)."""
    return any(path.startswith(prefix) for prefix in INTERNAL_ONLY_PREFIXES)


def is_internal_request(request: Request) -> bool:
    """Check if request is from agent-hub internal dashboard."""
    internal_header = request.headers.get(INTERNAL_SERVICE_HEADER)
    return internal_header == settings.internal_service_secret


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

        # Skip non-API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip exempt paths (truly public: health checks, docs, webhooks, websocket)
        if is_path_exempt(path):
            return await call_next(request)

        # Check internal-only paths (dashboard endpoints that require internal header)
        if is_internal_only_path(path):
            if is_internal_request(request):
                logger.debug(f"Internal request to dashboard endpoint: {path}")
                request.state.client = None
                request.state.client_id = None
                request.state.request_source = "agent-hub-dashboard"
                request.state.is_internal = True
                return await call_next(request)
            else:
                # Internal-only paths require the internal header
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "internal_only",
                        "message": "This endpoint is only accessible from the Agent Hub dashboard",
                    },
                )

        # Skip internal agent-hub dashboard calls (for non-internal-only paths)
        if is_internal_request(request):
            logger.debug(f"Internal request bypassing auth: {path}")
            # Set request.state for downstream handlers
            request.state.client = None
            request.state.client_id = None
            request.state.request_source = "agent-hub-dashboard"
            request.state.is_internal = True
            return await call_next(request)

        # Get auth headers
        client_id = request.headers.get(CLIENT_ID_HEADER)
        client_secret = request.headers.get(CLIENT_SECRET_HEADER)
        request_source = request.headers.get(REQUEST_SOURCE_HEADER)
        source_client = request.headers.get(SOURCE_CLIENT_HEADER)
        tool_name = request.headers.get(TOOL_NAME_HEADER)
        source_path = request.headers.get(SOURCE_PATH_HEADER)

        # Detect tool type from X-Source-Client header
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
            await self._log_request(
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
            return JSONResponse(
                status_code=400,
                content={
                    "error": "missing_required_headers",
                    "message": f"Required headers missing: {', '.join(missing_headers)}",
                    "required_headers": [
                        CLIENT_ID_HEADER,
                        CLIENT_SECRET_HEADER,
                        REQUEST_SOURCE_HEADER,
                    ],
                },
            )

        # Authenticate client (cached lookup + cached bcrypt verification)
        # client_id is guaranteed non-None at this point (checked in missing_headers)
        assert client_id is not None
        try:
            client_data = await _get_cached_client(client_id)

            if not client_data:
                await self._log_request(
                    client_id=client_id,
                    request_source=request_source,
                    endpoint=path,
                    method=method,
                    status_code=403,
                    rejection_reason="authentication_failed",
                    latency_ms=int((time.time() - start_time) * 1000),
                    tool_type=tool_type,
                    tool_name=tool_name,
                    source_path=source_path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "authentication_failed",
                        "message": "Client not found or invalid credentials",
                    },
                )

            # Verify secret (cached - avoids 190ms bcrypt on repeat requests)
            assert client_secret is not None
            if not verify_secret(client_secret, client_data["secret_hash"], client_id=client_id):
                await self._log_request(
                    client_id=client_id,
                    request_source=request_source,
                    endpoint=path,
                    method=method,
                    status_code=403,
                    rejection_reason="authentication_failed",
                    latency_ms=int((time.time() - start_time) * 1000),
                    tool_type=tool_type,
                    tool_name=tool_name,
                    source_path=source_path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "authentication_failed",
                        "message": "Client not found or invalid credentials",
                    },
                )

            # Check client status
            if client_data["status"] == "suspended":
                await self._log_request(
                    client_id=client_id,
                    request_source=request_source,
                    endpoint=path,
                    method=method,
                    status_code=403,
                    rejection_reason="client_suspended",
                    latency_ms=int((time.time() - start_time) * 1000),
                    tool_type=tool_type,
                    tool_name=tool_name,
                    source_path=source_path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "client_suspended",
                        "message": f"Client '{client_data['display_name']}' is suspended",
                        "reason": client_data["suspension_reason"],
                        "suspended_at": client_data["suspended_at"].isoformat()
                        if client_data["suspended_at"]
                        else None,
                        "contact": "Contact admin to restore access",
                    },
                )

            if client_data["status"] == "blocked":
                await self._log_request(
                    client_id=client_id,
                    request_source=request_source,
                    endpoint=path,
                    method=method,
                    status_code=403,
                    rejection_reason="client_blocked",
                    latency_ms=int((time.time() - start_time) * 1000),
                    tool_type=tool_type,
                    tool_name=tool_name,
                    source_path=source_path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "client_blocked",
                        "message": f"Client '{client_data['display_name']}' is permanently blocked",
                        "reason": client_data["suspension_reason"],
                        "blocked_at": client_data["suspended_at"].isoformat()
                        if client_data["suspended_at"]
                        else None,
                    },
                )

            # Attach authenticated client to request.state
            request.state.client = client_data.get("_client_obj")
            request.state.client_id = client_data["id"]
            request.state.request_source = request_source
            request.state.is_internal = False

        except Exception as e:
            logger.error(f"Access control check failed: {e}")
            # Fail closed - deny access if authentication check fails
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "Authentication service unavailable",
                },
            )

        # Process request
        response = await call_next(request)

        # Log successful request (async, fire and forget)
        latency_ms = int((time.time() - start_time) * 1000)

        # Capture agent_slug from request.state if set by route handler
        agent_slug = getattr(request.state, "agent_slug", None)

        await self._log_request(
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

    async def _log_request(
        self,
        client_id: str | None,
        request_source: str | None,
        endpoint: str,
        method: str,
        status_code: int,
        rejection_reason: str | None,
        latency_ms: int,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        model: str | None = None,
        session_id: str | None = None,
        agent_slug: str | None = None,
        tool_type: str = "api",
        tool_name: str | None = None,
        source_path: str | None = None,
    ) -> None:
        """Log request to request_logs table."""
        try:
            async for db in get_db():
                log_entry = RequestLog(
                    client_id=client_id,
                    request_source=request_source,
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    rejection_reason=rejection_reason,
                    latency_ms=latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model,
                    session_id=session_id,
                    agent_slug=agent_slug,
                    tool_type=tool_type,
                    tool_name=tool_name,
                    source_path=source_path,
                )
                db.add(log_entry)
                await db.commit()
                break
        except Exception as e:
            logger.warning(f"Failed to log request: {e}")
