"""Request logging for access control middleware."""

import logging

from app.db import async_session
from app.models import RequestLog

logger = logging.getLogger(__name__)


async def log_request(
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
    timed_out: bool = False,
    used_fallback: bool = False,
    fallback_model: str | None = None,
) -> None:
    """Log request to request_logs table."""
    try:
        async with async_session() as db:
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
                timed_out=timed_out,
                used_fallback=used_fallback,
                fallback_model=fallback_model,
            )
            db.add(log_entry)
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log request: {e}")


async def log_rejection(
    path: str,
    method: str,
    start_time: float,
    client_id: str,
    request_source: str | None,
    tool_type: str,
    tool_name: str | None,
    source_path: str | None,
    rejection_reason: str,
) -> None:
    """Log a rejected request."""
    import time

    await log_request(
        client_id=client_id,
        request_source=request_source,
        endpoint=path,
        method=method,
        status_code=403,
        rejection_reason=rejection_reason,
        latency_ms=int((time.time() - start_time) * 1000),
        tool_type=tool_type,
        tool_name=tool_name,
        source_path=source_path,
    )
