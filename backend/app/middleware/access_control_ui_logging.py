"""Sampled request_logs telemetry for internal dashboard (UI) requests.

Requests carrying the internal header skip client identification and were never
logged, so UI usage was invisible. A sampled fraction is now written to
``request_logs`` with ``request_source='agent-hub-dashboard-ui'``.

Rows record method, route template, status, latency and the dashboard client id
(when registered). No bodies, headers or secrets. ``model`` and ``agent_slug``
stay null and ``/api/complete`` is excluded, so model-call stats never count
UI rows. The write runs as a background task off the request path and never
raises.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.middleware.access_control_auth import get_cached_client
from app.middleware.access_control_constants import CLIENT_ID_HEADER
from app.middleware.access_control_logging import log_request

logger = logging.getLogger(__name__)

UI_REQUEST_SOURCE = "agent-hub-dashboard-ui"
DEFAULT_UI_SAMPLE_RATE = 0.1

# Noisy, streaming or already-logged paths. Prefix match.
UI_LOG_EXCLUDED_PREFIXES = (
    "/api/complete",  # Model calls: logged by the identified path; must not enter model-call stats
    "/api/dashboard",  # Already logged as an auth-bypass path
    "/api/health",
    "/api/status",
    "/api/memory/capture/stream",  # SSE
    "/_next",
    "/static",
)

# Strong references so pending log tasks are not garbage-collected mid-flight.
_pending_tasks: set[asyncio.Task[None]] = set()


def ui_sample_rate() -> float:
    """Configured sample rate clamped to [0, 1]; invalid values disable logging."""
    raw = getattr(settings, "dashboard_ui_request_log_sample_rate", DEFAULT_UI_SAMPLE_RATE)
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if rate != rate:  # NaN
        return 0.0
    return min(max(rate, 0.0), 1.0)


def is_ui_log_excluded(path: str) -> bool:
    """True for paths UI sampling must never log."""
    if any(path.startswith(prefix) for prefix in UI_LOG_EXCLUDED_PREFIXES):
        return True
    segments = path.rstrip("/").split("/")
    return "stream" in segments or "health" in segments


def should_sample(rate: float, rng: Callable[[], float] = random.random) -> bool:
    """Bernoulli sample: rate 0 never logs, rate 1 always logs."""
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    return rng() < rate


def route_template(request: Request) -> str:
    """Matched route path template (e.g. ``/api/agents/{slug}``), else the raw path."""
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return request.url.path


def _is_event_stream(response: Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return content_type.startswith("text/event-stream")


async def _write_ui_log(
    raw_client_id: str | None, endpoint: str, method: str, status_code: int, latency_ms: int
) -> None:
    try:
        client_id: str | None = None
        if raw_client_id:
            # request_logs.client_id is a FK; only attribute registered clients.
            client = await get_cached_client(raw_client_id)
            client_id = client["id"] if client else None
        await log_request(
            client_id=client_id,
            request_source=UI_REQUEST_SOURCE,
            endpoint=endpoint[:200],
            method=method,
            status_code=status_code,
            rejection_reason=None,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.warning("Failed to log dashboard UI request: %s", exc)


def schedule_ui_request_log(
    request: Request,
    response: Response,
    method: str,
    start_time: float,
    rng: Callable[[], float] = random.random,
) -> asyncio.Task[None] | None:
    """Sample and schedule a background request_logs write. Never raises."""
    try:
        path = request.url.path
        if is_ui_log_excluded(path) or _is_event_stream(response):
            return None
        if not should_sample(ui_sample_rate(), rng):
            return None
        latency_ms = int((time.time() - start_time) * 1000)
        task = asyncio.create_task(
            _write_ui_log(
                request.headers.get(CLIENT_ID_HEADER),
                route_template(request),
                method,
                response.status_code,
                latency_ms,
            )
        )
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
        return task
    except Exception as exc:
        logger.warning("Failed to schedule dashboard UI request log: %s", exc)
        return None
