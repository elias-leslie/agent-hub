"""Kill switch middleware for usage control.

Checks X-Source-Client and X-Source-Path headers against kill switch controls.
Blocks requests from disabled clients with 403 response.
"""

import logging
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.admin import log_blocked_request, log_request_audit
from app.db import get_db
from app.models import ClientControl

logger = logging.getLogger(__name__)

# Headers for source attribution
SOURCE_CLIENT_HEADER = "X-Source-Client"
SOURCE_PATH_HEADER = "X-Source-Path"

# Endpoints that don't require source headers (admin, health, docs)
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
    ]
)

# Path prefixes exempt from kill switch (only admin endpoints)
EXEMPT_PREFIXES = (
    "/api/admin",  # Admin endpoints for managing the killswitch itself
)

# Internal service header for agent-hub self-calls
INTERNAL_SERVICE_HEADER = "X-Agent-Hub-Internal"
INTERNAL_SERVICE_SECRET = "agent-hub-internal-v1"  # TODO: Move to env var

# Kill switch enforcement mode:
# - "audit": Log unknown clients but DON'T block them (for visibility/discovery)
# - "enforce": Block unknown clients with 400 error
# Start in audit mode to discover what's connecting, then switch to enforce
KILL_SWITCH_MODE = "audit"  # Change to "enforce" once you've identified all clients


def is_path_exempt(path: str) -> bool:
    """Check if path is exempt from kill switch checks."""
    # Exact matches
    if path in EXEMPT_PATHS:
        return True
    # Prefix matches for admin endpoints only
    return path.startswith(EXEMPT_PREFIXES)


def is_internal_request(request: Request) -> bool:
    """Check if request is from agent-hub internal service."""
    internal_header = request.headers.get(INTERNAL_SERVICE_HEADER)
    return internal_header == INTERNAL_SERVICE_SECRET


class BlockedRequestError(HTTPException):
    """Exception raised when a request is blocked by kill switch."""

    def __init__(
        self,
        error_type: str,
        message: str,
        blocked_entity: str,
        reason: str | None = None,
        disabled_at: str | None = None,
    ):
        self.error_type = error_type
        self.message = message
        self.blocked_entity = blocked_entity
        self.reason = reason
        self.disabled_at = disabled_at
        super().__init__(
            status_code=403,
            detail={
                "error": error_type,
                "message": message,
                "blocked_entity": blocked_entity,
                "reason": reason,
                "disabled_at": disabled_at,
                "retry_after": -1,  # -1 means permanent block until manually re-enabled
                "contact": "Contact admin to re-enable access",
            },
            headers={"Retry-After": "-1"},  # HTTP-compliant header
        )


async def check_kill_switch(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_source_client: Annotated[str | None, Header(alias=SOURCE_CLIENT_HEADER)] = None,
    x_source_path: Annotated[str | None, Header(alias=SOURCE_PATH_HEADER)] = None,
) -> None:
    """FastAPI dependency to check kill switch status.

    Use this as a dependency on protected endpoints:
        @router.post("/complete", dependencies=[Depends(check_kill_switch)])

    Raises:
        HTTPException(400): Missing required source headers
        BlockedRequestError(403): Client is disabled
    """
    path = request.url.path

    # Skip exempt paths
    if is_path_exempt(path):
        return

    # Skip internal agent-hub self-calls
    if is_internal_request(request):
        logger.debug(f"Internal request bypassing killswitch: {path}")
        return

    # Require source headers on non-exempt paths
    if not x_source_client:
        logger.warning(f"Missing {SOURCE_CLIENT_HEADER} header on {path}")
        log_blocked_request(
            client_name="<unknown>",
            source_path=x_source_path,
            block_reason="missing_source_header: X-Source-Client header not provided",
            endpoint=path,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_source_header",
                "message": f"Required header {SOURCE_CLIENT_HEADER} is missing",
                "required_headers": [SOURCE_CLIENT_HEADER, SOURCE_PATH_HEADER],
            },
        )

    # Source path is optional but recommended
    if not x_source_path:
        logger.debug(f"Missing {SOURCE_PATH_HEADER} header on {path} from {x_source_client}")

    # Check client block
    result = await db.execute(
        select(ClientControl).where(ClientControl.client_name == x_source_client)
    )
    client = result.scalar_one_or_none()
    if client and not client.enabled:
        logger.warning(
            f"Blocked request: client={x_source_client} "
            f"(disabled by {client.disabled_by}: {client.reason})"
        )
        log_blocked_request(
            client_name=x_source_client,
            source_path=x_source_path,
            block_reason=f"client_disabled: {client.reason or 'No reason provided'}",
            endpoint=path,
        )
        raise BlockedRequestError(
            error_type="client_disabled",
            message=f"Client '{x_source_client}' is disabled",
            blocked_entity=x_source_client,
            reason=client.reason,
            disabled_at=client.disabled_at.isoformat() if client.disabled_at else None,
        )

    # Request allowed
    logger.debug(f"Allowed request: client={x_source_client}, path={path}")


# Endpoints that should be tracked in the audit log (LLM calls, expensive operations)
AUDIT_ENDPOINTS = (
    "/api/complete",
    "/api/stream",
    "/api/v1/chat/completions",
    "/api/sessions",
    "/api/credentials",
    "/api/api-keys",
)


def should_audit_request(path: str) -> bool:
    """Check if request should be logged to audit trail."""
    return any(path.startswith(ep) for ep in AUDIT_ENDPOINTS)


class KillSwitchMiddleware(BaseHTTPMiddleware):
    """Middleware version of kill switch check.

    Alternative to using check_kill_switch as a dependency.
    Provides global protection for all API endpoints.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Check kill switch before processing request."""
        path = request.url.path

        # Skip exempt paths
        if is_path_exempt(path):
            return await call_next(request)

        # Skip internal agent-hub self-calls
        if is_internal_request(request):
            logger.debug(f"Internal request bypassing killswitch: {path}")
            return await call_next(request)

        # Get headers and identification info
        x_source_client = request.headers.get(SOURCE_CLIENT_HEADER)
        x_source_path = request.headers.get(SOURCE_PATH_HEADER)
        user_agent = request.headers.get("User-Agent")
        referer = request.headers.get("Referer")
        client_ip = request.client.host if request.client else None

        # Only check /api/* paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Handle unknown clients (missing X-Source-Client header)
        if not x_source_client:
            # Always log to audit for visibility
            if should_audit_request(path):
                log_request_audit(
                    endpoint=path,
                    method=request.method,
                    client_name=None,
                    source_path=x_source_path,
                    user_agent=user_agent,
                    referer=referer,
                    client_ip=client_ip,
                    status="unknown_client",
                )

            if KILL_SWITCH_MODE == "enforce":
                # Enforce mode: Block unknown clients
                log_blocked_request(
                    client_name="<unknown>",
                    source_path=x_source_path,
                    block_reason="missing_source_header: X-Source-Client header not provided",
                    endpoint=path,
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "missing_source_header",
                        "message": f"Required header {SOURCE_CLIENT_HEADER} is missing",
                        "required_headers": [SOURCE_CLIENT_HEADER, SOURCE_PATH_HEADER],
                    },
                )
            else:
                # Audit mode: Log but allow the request through
                logger.info(
                    f"AUDIT: Unknown client accessing {path} "
                    f"(UA: {user_agent[:50] if user_agent else 'none'}, IP: {client_ip})"
                )
                # Skip database checks and allow request
                return await call_next(request)

        # Check kill switch using database session (only if we have a client name)
        try:
            async for db in get_db():
                # Check client block (and auto-register if new)
                result = await db.execute(
                    select(ClientControl).where(ClientControl.client_name == x_source_client)
                )
                client = result.scalar_one_or_none()

                # Auto-register new clients so they appear in Admin UI
                if client is None:
                    try:
                        new_client = ClientControl(
                            client_name=x_source_client,
                            enabled=True,  # Allow by default
                        )
                        db.add(new_client)
                        await db.commit()
                        logger.info(f"Auto-registered new client: {x_source_client}")
                    except Exception as reg_err:
                        # Non-fatal - might be race condition, client already exists
                        logger.debug(f"Client auto-registration skipped: {reg_err}")
                        await db.rollback()

                if client and not client.enabled:
                    if should_audit_request(path):
                        log_request_audit(
                            endpoint=path,
                            method=request.method,
                            client_name=x_source_client,
                            source_path=x_source_path,
                            user_agent=user_agent,
                            referer=referer,
                            client_ip=client_ip,
                            status="blocked",
                        )
                    log_blocked_request(
                        client_name=x_source_client,
                        source_path=x_source_path,
                        block_reason=f"client_disabled: {client.reason or 'No reason provided'}",
                        endpoint=path,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "client_disabled",
                            "message": f"Client '{x_source_client}' is disabled",
                            "blocked_entity": x_source_client,
                            "reason": client.reason,
                            "disabled_at": client.disabled_at.isoformat()
                            if client.disabled_at
                            else None,
                            "retry_after": -1,
                            "contact": "Contact admin to re-enable access",
                        },
                        headers={"Retry-After": "-1"},
                    )
                break
        except Exception as e:
            logger.error(f"Kill switch check failed: {e}")
            # Fail open - allow request if DB check fails
            # This is a deliberate choice to avoid breaking the system if DB is down

        # Log allowed requests to audit trail
        if should_audit_request(path):
            log_request_audit(
                endpoint=path,
                method=request.method,
                client_name=x_source_client,
                source_path=x_source_path,
                user_agent=user_agent,
                referer=referer,
                client_ip=client_ip,
                status="allowed",
            )

        return await call_next(request)
