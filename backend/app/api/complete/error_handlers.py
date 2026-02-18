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
    db: AsyncSession | None, session_id: str, error_type: str, error_message: str,
    agent_id: str | None = None, model_used: str | None = None,
) -> None:
    """Store an ERROR SessionEvent for observability (best-effort)."""
    if not db or not session_id:
        return
    try:
        from app.services.event_storage import store_error_event
        await store_error_event(
            db, session_id, error_type, error_message,
            agent_id=agent_id, model_used=model_used,
        )
        await db.commit()
    except Exception:
        logger.debug("Failed to store error event (non-critical)", exc_info=True)


async def _notify_error(
    session_id: str | None,
    db: AsyncSession | None,
    error_type: str,
    error_message: str,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> None:
    """Publish error event and store it in DB (best-effort)."""
    if not session_id:
        return
    await publish_error(session_id, error_type, error_message)
    await _store_error_event(db, session_id, error_type, error_message, agent_id, model_used)


async def handle_completion_error(
    error: Exception,
    session_id: str | None = None,
    db: AsyncSession | None = None,
    agent_id: str | None = None,
    model_used: str | None = None,
) -> NoReturn:
    """Handle completion errors and convert to HTTPException.

    Args:
        error: The exception that occurred
        session_id: Session ID for error tracking

    Raises:
        HTTPException: Always raises with appropriate error details
    """
    if isinstance(error, ValueError):
        logger.error(f"Configuration error: {error}")
        await _notify_error(session_id, db, "ConfigurationError", str(error), agent_id, model_used)
        raise HTTPException(status_code=500, detail=f"Configuration error: {error}") from error

    if isinstance(error, RateLimitError):
        logger.warning(f"Rate limit for {error.provider}")
        await _notify_error(session_id, db, "RateLimitError", str(error), agent_id, model_used)
        retry_after = str(int(error.retry_after)) if error.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {error.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from error

    if isinstance(error, AuthenticationError):
        logger.error(f"Auth error for {error.provider}")
        await _notify_error(session_id, db, "AuthenticationError", str(error), agent_id, model_used)
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {error.provider}. Check credentials in Settings or environment.",
        ) from error

    if isinstance(error, ProviderError):
        logger.error(f"Provider error: {error}")
        await _notify_error(session_id, db, "ProviderError", str(error), agent_id, model_used)
        raise HTTPException(status_code=error.status_code or 500, detail=str(error)) from error

    if isinstance(error, HTTPException):
        raise error
    logger.exception(f"Unexpected error in /complete: {error}")
    await _notify_error(session_id, db, "UnexpectedError", str(error), agent_id, model_used)
    raise HTTPException(status_code=500, detail="Internal server error.") from error
