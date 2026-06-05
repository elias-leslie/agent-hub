"""Path classification for access control middleware.

Defines which endpoints are exempt from authentication, require internal headers, etc.
"""

from starlette.requests import Request

from app.config import settings

# Endpoints exempt from authentication (health, docs, static)
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
        "/favicon.ico",
    ]
)

# Path prefixes exempt from authentication (no auth, no logging)
# MINIMAL: Only truly public endpoints or special auth (WebSocket, webhooks)
EXEMPT_PREFIXES = (
    "/ws/",  # WebSocket connections (uses different auth model)
    "/api/webhooks",  # Webhook delivery (uses signature verification)
    "/api/memory/capture/stream",  # SSE stream (BaseHTTPMiddleware buffers streaming responses)
    "/api/push/vapid-key",  # Public VAPID key for browser push subscription
)

# Path prefixes that bypass auth but still log requests
# For internal tools that don't need access control overhead but want telemetry
AUTH_BYPASS_PREFIXES = (
    "/api/dashboard",  # Dashboard stats (frontend only, no LLM costs)
    "/api/memory/search",  # Memory search (read-only)
    "/api/memory/episodes",  # Memory episode listing (read-only)
    "/api/memory/entities",  # Memory entity listing (read-only)
    "/api/agents",  # Agent discovery (read-only metadata, no LLM costs)
    "/api/models",  # Model catalog (read-only static data, no LLM costs)
    "/api/voice",  # Voice STT/TTS (free edge-tts + local whisper, no LLM costs)
)

# Path prefixes that require INTERNAL header (dashboard-only, not public)
# These bypass full auth but require X-Agent-Hub-Internal header
INTERNAL_ONLY_PREFIXES = (
    "/api/admin",  # Admin dashboard endpoints
    "/api/access-control",  # Access control management
    "/api/runtime-context",  # Runtime prompt/memory injection controls
    "/api/settings",  # Settings management
)

# Internal service header for agent-hub dashboard self-calls
INTERNAL_SERVICE_HEADER = "X-Agent-Hub-Internal"


def is_path_exempt(path: str) -> bool:
    """Check if path is exempt from authentication."""
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def is_auth_bypass_path(path: str) -> bool:
    """Check if path bypasses auth but still logs requests."""
    return any(path.startswith(prefix) for prefix in AUTH_BYPASS_PREFIXES)


def is_internal_only_path(path: str) -> bool:
    """Check if path requires internal header (dashboard-only endpoints)."""
    return any(path.startswith(prefix) for prefix in INTERNAL_ONLY_PREFIXES)


def is_internal_request(request: Request) -> bool:
    """Check if request is from agent-hub internal dashboard."""
    if not settings.internal_service_secret:
        return False
    internal_header = request.headers.get(INTERNAL_SERVICE_HEADER)
    return internal_header == settings.internal_service_secret
