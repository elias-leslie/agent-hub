"""Error handling for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

from fastapi import HTTPException

from app.adapters.base import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
)
from app.services.events import publish_error

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _store_error_event(
    db: AsyncSession | None, session_id: str, error_type: str, error_message: str
) -> None:
    """Store an ERROR SessionEvent for observability (best-effort)."""
    if not db or not session_id:
        return
    try:
        from app.services.event_storage import store_error_event

        await store_error_event(db, session_id, error_type, error_message)
        await db.commit()
    except Exception:
        logger.debug("Failed to store error event (non-critical)", exc_info=True)


async def handle_completion_error(
    error: Exception,
    session_id: str | None = None,
    db: AsyncSession | None = None,
) -> NoReturn:
    """Handle completion errors and convert to HTTPException.

    Args:
        error: The exception that occurred
        session_id: Session ID for error tracking

    Returns:
        HTTPException with appropriate status code and detail

    Raises:
        HTTPException: Always raises with appropriate error details
    """
    if isinstance(error, ValueError):
        logger.error(f"Configuration error: {error}")
        if session_id:
            await publish_error(session_id, "ConfigurationError", str(error))
            await _store_error_event(db, session_id, "ConfigurationError", str(error))
        raise HTTPException(status_code=500, detail=f"Configuration error: {error}") from error

    if isinstance(error, RateLimitError):
        logger.warning(f"Rate limit for {error.provider}")
        if session_id:
            await publish_error(session_id, "RateLimitError", str(error))
            await _store_error_event(db, session_id, "RateLimitError", str(error))
        retry_after = str(int(error.retry_after)) if error.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {error.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from error

    if isinstance(error, AuthenticationError):
        logger.error(f"Auth error for {error.provider}")
        if session_id:
            await publish_error(session_id, "AuthenticationError", str(error))
            await _store_error_event(db, session_id, "AuthenticationError", str(error))
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {error.provider}. Check credentials in Settings or environment.",
        ) from error

    if isinstance(error, ProviderError):
        logger.error(f"Provider error: {error}")
        if session_id:
            await publish_error(session_id, "ProviderError", str(error))
            await _store_error_event(db, session_id, "ProviderError", str(error))
        raise HTTPException(status_code=error.status_code or 500, detail=str(error)) from error

    if isinstance(error, HTTPException):
        raise error

    # Generic error handler
    logger.exception(f"Unexpected error in /complete: {error}")
    if session_id:
        await publish_error(session_id, "UnexpectedError", str(error))
        await _store_error_event(db, session_id, "UnexpectedError", str(error))
    raise HTTPException(status_code=500, detail="Internal server error.") from error
