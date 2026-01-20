"""Kill switch middleware for usage control.

Checks X-Source-Client and X-Source-Path headers against kill switch controls.
Blocks requests from disabled clients/purposes with 403 response.

Check hierarchy (first match wins):
1. ClientPurposeControl (client, purpose) combo
2. ClientControl (client)
3. PurposeControl (purpose)
"""

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.admin import log_blocked_request
from app.db import get_db
from app.models import ClientControl, ClientPurposeControl, PurposeControl

logger = logging.getLogger(__name__)

# Headers for source attribution
SOURCE_CLIENT_HEADER = "X-Source-Client"
SOURCE_PATH_HEADER = "X-Source-Path"

# Endpoints that don't require source headers (admin, health, docs, dashboard)
EXEMPT_PATHS = frozenset(
    [
        "/",
        "/health",
        "/status",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/admin",  # Admin endpoints exempt
        "/api/health",
        "/api/status",
    ]
)

# Path prefixes exempt from kill switch (dashboard/internal endpoints)
EXEMPT_PREFIXES = (
    "/api/admin",
    "/api/memory",  # Memory dashboard
    "/api/sessions",  # Sessions dashboard
    "/api/projects",  # Project management
    "/api/tools",  # Internal tools (dependency check, etc.)
    "/api/agents",  # Agent management dashboard
)


def is_path_exempt(path: str) -> bool:
    """Check if path is exempt from kill switch checks."""
    # Exact matches
    if path in EXEMPT_PATHS:
        return True
    # Prefix matches for dashboard/internal endpoints
    return path.startswith(EXEMPT_PREFIXES)


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
        BlockedRequestError(403): Client/purpose is disabled
    """
    path = request.url.path

    # Skip exempt paths
    if is_path_exempt(path):
        return

    # Require source headers on non-exempt paths
    if not x_source_client:
        logger.warning(f"Missing {SOURCE_CLIENT_HEADER} header on {path}")
        log_blocked_request(
            client_name="<unknown>",
            purpose=request.headers.get("X-Purpose") or request.query_params.get("purpose"),
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

    # Check kill switch controls in priority order:
    # 1. Client+Purpose combo (most specific)
    # 2. Client
    # 3. Purpose

    # Extract purpose from request (if available via session or header)
    purpose = request.headers.get("X-Purpose") or request.query_params.get("purpose")

    # 1. Check combo block (client + purpose)
    if purpose:
        result = await db.execute(
            select(ClientPurposeControl).where(
                ClientPurposeControl.client_name == x_source_client,
                ClientPurposeControl.purpose == purpose,
            )
        )
        combo = result.scalar_one_or_none()
        if combo and not combo.enabled:
            logger.warning(
                f"Blocked request: client={x_source_client}, purpose={purpose} "
                f"(combo disabled by {combo.disabled_by}: {combo.reason})"
            )
            log_blocked_request(
                client_name=x_source_client,
                purpose=purpose,
                source_path=x_source_path,
                block_reason=f"client_purpose_combo_disabled: {combo.reason or 'No reason provided'}",
                endpoint=path,
            )
            raise BlockedRequestError(
                error_type="client_purpose_disabled",
                message=f"Client '{x_source_client}' is disabled for purpose '{purpose}'",
                blocked_entity=f"{x_source_client}:{purpose}",
                reason=combo.reason,
                disabled_at=combo.disabled_at.isoformat() if combo.disabled_at else None,
            )

    # 2. Check client block
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
            purpose=purpose,
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

    # 3. Check purpose block
    if purpose:
        result = await db.execute(select(PurposeControl).where(PurposeControl.purpose == purpose))
        purpose_control = result.scalar_one_or_none()
        if purpose_control and not purpose_control.enabled:
            logger.warning(
                f"Blocked request: purpose={purpose} "
                f"(disabled by {purpose_control.disabled_by}: {purpose_control.reason})"
            )
            log_blocked_request(
                client_name=x_source_client,
                purpose=purpose,
                source_path=x_source_path,
                block_reason=f"purpose_disabled: {purpose_control.reason or 'No reason provided'}",
                endpoint=path,
            )
            raise BlockedRequestError(
                error_type="purpose_disabled",
                message=f"Purpose '{purpose}' is disabled",
                blocked_entity=purpose,
                reason=purpose_control.reason,
                disabled_at=purpose_control.disabled_at.isoformat()
                if purpose_control.disabled_at
                else None,
            )

    # Request allowed
    logger.debug(f"Allowed request: client={x_source_client}, purpose={purpose}, path={path}")


class KillSwitchMiddleware(BaseHTTPMiddleware):
    """Middleware version of kill switch check.

    Alternative to using check_kill_switch as a dependency.
    Provides global protection for all API endpoints.
    """

    async def dispatch(self, request: Request, call_next):
        """Check kill switch before processing request."""
        path = request.url.path

        # Skip exempt paths
        if is_path_exempt(path):
            return await call_next(request)

        # Get headers
        x_source_client = request.headers.get(SOURCE_CLIENT_HEADER)
        x_source_path = request.headers.get(SOURCE_PATH_HEADER)

        # Only check /api/* paths
        if not path.startswith("/api/"):
            return await call_next(request)

        # Require source client header
        if not x_source_client:
            log_blocked_request(
                client_name="<unknown>",
                purpose=request.headers.get("X-Purpose") or request.query_params.get("purpose"),
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

        # Check kill switch using database session
        try:
            async for db in get_db():
                purpose = request.headers.get("X-Purpose") or request.query_params.get("purpose")

                # Check combo block
                if purpose:
                    result = await db.execute(
                        select(ClientPurposeControl).where(
                            ClientPurposeControl.client_name == x_source_client,
                            ClientPurposeControl.purpose == purpose,
                        )
                    )
                    combo = result.scalar_one_or_none()
                    if combo and not combo.enabled:
                        log_blocked_request(
                            client_name=x_source_client,
                            purpose=purpose,
                            source_path=x_source_path,
                            block_reason=f"client_purpose_combo_disabled: {combo.reason or 'No reason provided'}",
                            endpoint=path,
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error": "client_purpose_disabled",
                                "message": f"Client '{x_source_client}' is disabled for purpose '{purpose}'",
                                "blocked_entity": f"{x_source_client}:{purpose}",
                                "reason": combo.reason,
                                "disabled_at": combo.disabled_at.isoformat()
                                if combo.disabled_at
                                else None,
                                "retry_after": -1,
                                "contact": "Contact admin to re-enable access",
                            },
                            headers={"Retry-After": "-1"},
                        )

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
                    log_blocked_request(
                        client_name=x_source_client,
                        purpose=purpose,
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

                # Check purpose block
                if purpose:
                    result = await db.execute(
                        select(PurposeControl).where(PurposeControl.purpose == purpose)
                    )
                    purpose_control = result.scalar_one_or_none()
                    if purpose_control and not purpose_control.enabled:
                        log_blocked_request(
                            client_name=x_source_client,
                            purpose=purpose,
                            source_path=x_source_path,
                            block_reason=f"purpose_disabled: {purpose_control.reason or 'No reason provided'}",
                            endpoint=path,
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error": "purpose_disabled",
                                "message": f"Purpose '{purpose}' is disabled",
                                "blocked_entity": purpose,
                                "reason": purpose_control.reason,
                                "disabled_at": purpose_control.disabled_at.isoformat()
                                if purpose_control.disabled_at
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

        return await call_next(request)
