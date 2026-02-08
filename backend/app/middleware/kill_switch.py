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

from app.api.admin_redis import log_blocked_request, log_request_audit
from app.db import async_session, get_db
from app.middleware.kill_switch_base import (
    AUDIT_ENDPOINTS,
    EXEMPT_PATHS,
    EXEMPT_PREFIXES,
    INTERNAL_SERVICE_HEADER,
    KILL_SWITCH_MODE,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
    is_internal_request,
    is_path_exempt,
    should_audit_request,
)
from app.models import ClientControl

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ENDPOINTS",
    "EXEMPT_PATHS",
    "EXEMPT_PREFIXES",
    "INTERNAL_SERVICE_HEADER",
    "KILL_SWITCH_MODE",
    "SOURCE_CLIENT_HEADER",
    "SOURCE_PATH_HEADER",
    "BlockedRequestError",
    "KillSwitchMiddleware",
    "check_kill_switch",
    "is_internal_request",
    "is_path_exempt",
    "should_audit_request",
]


class BlockedRequestError(HTTPException):
    """Exception raised when a request is blocked by kill switch."""

    def __init__(self, client_name: str, reason: str | None, disabled_at: str | None = None):
        detail = {
            "error": "client_disabled",
            "message": f"Client '{client_name}' is disabled",
            "blocked_entity": client_name,
            "reason": reason,
            "disabled_at": disabled_at,
            "retry_after": -1,
            "contact": "Contact admin to re-enable access",
        }
        super().__init__(status_code=403, detail=detail, headers={"Retry-After": "-1"})


async def check_kill_switch(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_source_client: Annotated[str | None, Header(alias=SOURCE_CLIENT_HEADER)] = None,
    x_source_path: Annotated[str | None, Header(alias=SOURCE_PATH_HEADER)] = None,
) -> None:
    """FastAPI dependency to check kill switch status."""
    path = request.url.path
    if is_path_exempt(path) or is_internal_request(request):
        return

    if not x_source_client:
        await log_blocked_request("<unknown>", x_source_path, "missing_source_header: X-Source-Client missing", path)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_source_header",
                "message": f"Required header {SOURCE_CLIENT_HEADER} is missing",
                "required_headers": [SOURCE_CLIENT_HEADER, SOURCE_PATH_HEADER],
            },
        )

    client = (await db.execute(select(ClientControl).where(ClientControl.client_name == x_source_client))).scalar_one_or_none()

    if client and not client.enabled:
        reason = client.reason or "No reason provided"
        await log_blocked_request(x_source_client, x_source_path, f"client_disabled: {reason}", path)
        raise BlockedRequestError(x_source_client, client.reason, client.disabled_at.isoformat() if client.disabled_at else None)


class KillSwitchMiddleware(BaseHTTPMiddleware):
    """Middleware version of kill switch check."""

    async def _handle_missing_client(self, request: Request, x_source_path: str | None) -> JSONResponse | None:
        path = request.url.path
        if should_audit_request(path):
            await log_request_audit(
                path, request.method, None, x_source_path,
                request.headers.get("User-Agent"), request.headers.get("Referer"),
                request.client.host if request.client else None, "unknown_client"
            )

        if KILL_SWITCH_MODE == "enforce":
            await log_blocked_request("<unknown>", x_source_path, "missing_source_header: X-Source-Client missing", path)
            return JSONResponse(
                status_code=400,
                content={
                    "error": "missing_source_header",
                    "message": f"Required header {SOURCE_CLIENT_HEADER} is missing",
                    "required_headers": [SOURCE_CLIENT_HEADER, SOURCE_PATH_HEADER],
                },
            )
        logger.info(f"AUDIT: Unknown client accessing {path}")
        return None

    async def _get_client_and_auto_reg(self, db: AsyncSession, client_name: str) -> ClientControl | None:
        client = (await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))).scalar_one_or_none()
        if client is None:
            try:
                client = ClientControl(client_name=client_name, enabled=True)
                db.add(client)
                await db.commit()
                logger.info(f"Auto-registered new client: {client_name}")
            except Exception as e:
                logger.debug(f"Client auto-registration skipped: {e}")
                await db.rollback()
                client = (await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))).scalar_one_or_none()
        return client

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        if is_path_exempt(path) or is_internal_request(request) or not path.startswith("/api/"):
            return await call_next(request)

        client_name, source_path = request.headers.get(SOURCE_CLIENT_HEADER), request.headers.get(SOURCE_PATH_HEADER)
        if not client_name:
            if resp := await self._handle_missing_client(request, source_path):
                return resp
            return await call_next(request)

        try:
            async with async_session() as db:
                client = await self._get_client_and_auto_reg(db, client_name)
                if client and not client.enabled:
                    if should_audit_request(path):
                        await log_request_audit(
                            path, request.method, client_name, source_path,
                            request.headers.get("User-Agent"), request.headers.get("Referer"),
                            request.client.host if request.client else None, "blocked"
                        )
                    await log_blocked_request(client_name, source_path, f"client_disabled: {client.reason or 'No reason provided'}", path)
                    err = BlockedRequestError(client_name, client.reason, client.disabled_at.isoformat() if client.disabled_at else None)
                    return JSONResponse(status_code=err.status_code, content=err.detail, headers=err.headers)
        except Exception as e:
            logger.error(f"Kill switch check failed: {e}")

        if should_audit_request(path):
            await log_request_audit(
                path, request.method, client_name, source_path,
                request.headers.get("User-Agent"), request.headers.get("Referer"),
                request.client.host if request.client else None, "allowed"
            )
        return await call_next(request)
