"""Shared FastAPI exception handlers for consistent error responses.

Synchronized copy -- also present in summitflow/backend/app/exception_handlers.py.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

try:
    import structlog  # ty: ignore[unresolved-import]
    logger = structlog.stdlib.get_logger(__name__)
except ModuleNotFoundError:
    logger = logging.getLogger(__name__)


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """Sanitize validation errors so ctx values are always JSON-serializable."""
    sanitized: list[dict[str, object]] = []
    for error in exc.errors():
        clean: dict[str, object] = {
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        if "ctx" in error:
            clean["ctx"] = {k: str(v) for k, v in error["ctx"].items()}
        sanitized.append(clean)
    return sanitized


def setup_exception_handlers(app: FastAPI) -> None:
    """Register RequestValidationError, HTTPException, and catch-all handlers."""

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "details": _sanitize_validation_errors(exc),
            },
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
                "details": [exc.detail] if not isinstance(exc.detail, str) else [],
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "details": [],
            },
        )
