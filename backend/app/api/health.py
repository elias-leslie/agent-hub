"""
Health, status, and metrics endpoints.

- /health: Basic liveness check
- /status: Detailed diagnostics (providers, database)
- /metrics: Prometheus format metrics
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Global metrics counters (simple in-memory for now)
_metrics: dict[str, Any] = {
    "request_count": 0,
    "error_count": 0,
    "active_sessions": 0,
    "latency_sum_ms": 0.0,
    "latency_count": 0,
}


class HealthResponse(BaseModel):
    """Basic health check response."""

    status: str
    service: str


class ProviderStatus(BaseModel):
    """Status of an AI provider."""

    name: str
    available: bool
    configured: bool
    error: str | None = None


class StatusResponse(BaseModel):
    """Detailed status response."""

    status: str
    service: str
    database: str
    providers: list[ProviderStatus]
    uptime_seconds: float


# Track server start time
_start_time = time.time()


def increment_request_count() -> None:
    """Increment the global request counter."""
    _metrics["request_count"] += 1


def increment_error_count() -> None:
    """Increment the global error counter."""
    _metrics["error_count"] += 1


def record_latency(latency_ms: float) -> None:
    """Record a request latency for histogram."""
    _metrics["latency_sum_ms"] += latency_ms
    _metrics["latency_count"] += 1


def set_active_sessions(count: int) -> None:
    """Set the number of active sessions."""
    _metrics["active_sessions"] = count


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Basic liveness check.

    Returns 200 OK if the service is running.
    """
    return HealthResponse(status="healthy", service="agent-hub")


@router.get("/status", response_model=StatusResponse)
async def status_check(db: AsyncSession = Depends(get_db)) -> StatusResponse:
    """
    Detailed diagnostics including provider and database status.
    """
    # Check database connection
    db_status = "unknown"
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.warning(f"Database check failed: {e}")
        db_status = f"error: {str(e)[:50]}"

    # Check providers
    providers: list[ProviderStatus] = []

    # Claude provider
    claude_configured = bool(settings.anthropic_api_key)
    claude_status = ProviderStatus(
        name="claude",
        available=False,
        configured=claude_configured,
    )
    if claude_configured:
        try:
            from app.adapters.claude import ClaudeAdapter

            adapter = ClaudeAdapter()
            claude_status.available = await adapter.health_check()
        except Exception as e:
            claude_status.error = str(e)[:100]
    providers.append(claude_status)

    # Gemini provider
    gemini_configured = bool(settings.gemini_api_key)
    gemini_status = ProviderStatus(
        name="gemini",
        available=False,
        configured=gemini_configured,
    )
    if gemini_configured:
        try:
            from app.adapters.gemini import GeminiAdapter

            adapter = GeminiAdapter()
            gemini_status.available = await adapter.health_check()
        except Exception as e:
            gemini_status.error = str(e)[:100]
    providers.append(gemini_status)

    # Determine overall status
    any_provider_available = any(p.available for p in providers)
    overall_status = "healthy" if db_status == "connected" and any_provider_available else "degraded"

    return StatusResponse(
        status=overall_status,
        service="agent-hub",
        database=db_status,
        providers=providers,
        uptime_seconds=time.time() - _start_time,
    )


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_db)) -> Response:
    """
    Prometheus format metrics.

    Returns metrics in Prometheus text exposition format.
    """
    # Get active session count from database
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM sessions WHERE status = 'active'"))
        active_sessions = result.scalar() or 0
        _metrics["active_sessions"] = active_sessions
    except Exception as e:
        logger.warning(f"Failed to get active sessions: {e}")

    # Calculate average latency
    avg_latency = 0.0
    if _metrics["latency_count"] > 0:
        avg_latency = _metrics["latency_sum_ms"] / _metrics["latency_count"]

    # Build Prometheus format output
    lines = [
        "# HELP agent_hub_requests_total Total number of requests",
        "# TYPE agent_hub_requests_total counter",
        f'agent_hub_requests_total {_metrics["request_count"]}',
        "",
        "# HELP agent_hub_errors_total Total number of errors",
        "# TYPE agent_hub_errors_total counter",
        f'agent_hub_errors_total {_metrics["error_count"]}',
        "",
        "# HELP agent_hub_active_sessions Number of active sessions",
        "# TYPE agent_hub_active_sessions gauge",
        f'agent_hub_active_sessions {_metrics["active_sessions"]}',
        "",
        "# HELP agent_hub_request_latency_ms Request latency histogram",
        "# TYPE agent_hub_request_latency_ms summary",
        f"agent_hub_request_latency_ms_sum {_metrics['latency_sum_ms']}",
        f"agent_hub_request_latency_ms_count {_metrics['latency_count']}",
        "",
        "# HELP agent_hub_uptime_seconds Service uptime in seconds",
        "# TYPE agent_hub_uptime_seconds gauge",
        f"agent_hub_uptime_seconds {time.time() - _start_time:.1f}",
        "",
    ]

    return Response(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
