"""Path classification for access control middleware.

Defines which endpoints are exempt from authentication, require internal headers, etc.
"""

from hmac import compare_digest

from starlette.requests import HTTPConnection

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
        "/api/auth/me",  # Caller identity for the dashboard proxy (no secrets)
        "/favicon.ico",
    ]
)

# Path prefixes exempt from authentication (no auth, no logging)
# MINIMAL: Only truly public endpoints or special auth (WebSocket, SSE)
EXEMPT_PREFIXES = (
    "/ws/",  # WebSocket connections (uses different auth model)
    "/api/memory/capture/stream",  # SSE stream (BaseHTTPMiddleware buffers streaming responses)
    "/api/host-credentials/",  # Remote host bearer token checked in the route; values never request-logged
    "/api/host-context/",  # Remote host bearer token checked in the route
    "/api/host-sessions/",  # Remote host bearer token checked in the route; bodies are transcripts
)

# Path prefixes whose GET/HEAD reads bypass identification but still log requests.
# Writes under them (agent edits, memory tags and ratings, model sync, TTS) need
# the internal header or a client id like every other write, so they are attributed.
AUTH_BYPASS_PREFIXES = (
    "/api/dashboard",  # Dashboard stats (frontend only, no LLM costs)
    "/api/memory/search",  # Memory search
    "/api/memory/episodes",  # Memory episode listing
    "/api/memory/entities",  # Memory entity listing
    "/api/agents",  # Agent discovery
    "/api/models",  # Model catalog (static data, no LLM costs)
    "/api/voice",  # Voice list (the WebSocket is outside this HTTP middleware)
)
_READ_METHODS = frozenset({"GET", "HEAD"})

# Path prefixes that require INTERNAL header (dashboard-only, not public)
# These bypass full auth but require X-Agent-Hub-Internal header
INTERNAL_ONLY_PREFIXES = (
    "/api/automations",  # Canonical automation administration and owner receipts
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


def is_auth_bypass_path(path: str, method: str = "GET") -> bool:
    """Check if path bypasses auth but still logs requests (reads only)."""
    if method not in _READ_METHODS:
        return False
    return any(path.startswith(prefix) for prefix in AUTH_BYPASS_PREFIXES)


def is_internal_only_path(path: str) -> bool:
    """Check if path requires internal header (dashboard-only endpoints)."""
    return any(path.startswith(prefix) for prefix in INTERNAL_ONLY_PREFIXES)


def is_internal_request(request: HTTPConnection) -> bool:
    """Check if a request or WebSocket carries the internal service secret."""
    if not settings.internal_service_secret:
        return False
    internal_header = request.headers.get(INTERNAL_SERVICE_HEADER)
    if internal_header is None:
        return False
    return compare_digest(internal_header.encode(), settings.internal_service_secret.encode())
