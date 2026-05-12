"""Error handling for completion API."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, NoReturn

from fastapi import HTTPException

from app.models import Session
from app.services.events import publish_error
from app.services.llm_errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
)
from app.services.session_health import health_detail_for_error
from app.services.session_live_activity import mark_session_terminal_state

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
        session = await db.get(Session, session_id)
        if session is not None:
            session.status = "failed"
            session.health_detail = health_detail_for_error(error_message)
            mark_session_terminal_state(
                session,
                phase="error",
                status="error",
                summary=f"{error_type}: {error_message[:120]}",
                termination_reason=f"{error_type}: {error_message}",
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


async def _handle_value_error(
    error: ValueError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle ValueError (configuration errors)."""
    logger.error(f"Configuration error: {error}")
    await _notify_error(session_id, db, "ConfigurationError", str(error), agent_id, model_used)
    raise HTTPException(status_code=500, detail=f"Configuration error: {error}") from error


def _build_rate_limit_summary(error: RateLimitError) -> str:
    """Build quota summary string from rate limit error details."""
    quota = error.quota_details
    if not quota.get("quota_metric"):
        return ""
    return (
        f" [metric={quota.get('quota_metric')}"
        f" limit={quota.get('quota_limit', '?')}"
        f" consumer={quota.get('consumer', '?')}]"
    )


async def _handle_rate_limit_error(
    error: RateLimitError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle RateLimitError with retry-after header."""
    quota_summary = _build_rate_limit_summary(error)
    logger.warning("Rate limit for %s%s", error.provider, quota_summary)
    error_detail = f"Rate limit exceeded for {error.provider}.{quota_summary}"
    await _notify_error(session_id, db, "RateLimitError", error_detail, agent_id, model_used)
    retry_after = str(int(error.retry_after)) if error.retry_after else "60"
    raise HTTPException(
        status_code=429,
        detail=f"{error_detail} Wait {retry_after}s before retrying the same provider.",
        headers={"Retry-After": retry_after},
    ) from error


async def _handle_auth_error(
    error: AuthenticationError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle AuthenticationError."""
    logger.error(f"Auth error for {error.provider}")
    await _notify_error(session_id, db, "AuthenticationError", str(error), agent_id, model_used)
    raise HTTPException(
        status_code=401,
        detail=f"Authentication failed for {error.provider}. Check credentials in Settings or environment.",
    ) from error


async def _handle_provider_error(
    error: ProviderError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle ProviderError."""
    logger.error(f"Provider error: {error}")
    await _notify_error(session_id, db, "ProviderError", str(error), agent_id, model_used)
    raise HTTPException(status_code=error.status_code or 500, detail=str(error)) from error


async def _handle_timeout_error(
    error: TimeoutError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle TimeoutError."""
    logger.error(f"Timeout error: {error}")
    await _notify_error(session_id, db, "TimeoutError", str(error), agent_id, model_used)
    raise HTTPException(status_code=504, detail=str(error)) from error


async def _handle_cancelled_error(
    error: asyncio.CancelledError,
    session_id: str | None,
    db: AsyncSession | None,
    agent_id: str | None,
    model_used: str | None,
) -> NoReturn:
    """Handle unexpected cancellation in non-streaming completion flow."""
    message = str(error) or "Completion cancelled unexpectedly."
    logger.error("Completion cancelled unexpectedly: %s", message)
    await _notify_error(session_id, db, "CancelledError", message, agent_id, model_used)
    raise HTTPException(status_code=500, detail="Completion cancelled unexpectedly.") from error


async def handle_completion_error(
    error: BaseException,
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
        await _handle_value_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, RateLimitError):
        await _handle_rate_limit_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, AuthenticationError):
        await _handle_auth_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, ProviderError):
        await _handle_provider_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, TimeoutError):
        await _handle_timeout_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, asyncio.CancelledError):
        await _handle_cancelled_error(error, session_id, db, agent_id, model_used)

    if isinstance(error, HTTPException):
        raise error

    logger.exception(f"Unexpected error in /complete: {error}")
    await _notify_error(session_id, db, "UnexpectedError", str(error), agent_id, model_used)
    raise HTTPException(status_code=500, detail="Internal server error.") from error
