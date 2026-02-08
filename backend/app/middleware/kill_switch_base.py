"""Base constants and helpers for kill switch middleware."""

import logging
from typing import Final

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

# Headers for source attribution
SOURCE_CLIENT_HEADER: Final = "X-Source-Client"
SOURCE_PATH_HEADER: Final = "X-Source-Path"
INTERNAL_SERVICE_HEADER: Final = "X-Agent-Hub-Internal"

# Kill switch enforcement mode: "audit" or "enforce"
# Start in audit mode to discover what's connecting, then switch to enforce
KILL_SWITCH_MODE = "audit"

# Endpoints that don't require source headers (admin, health, docs)
EXEMPT_PATHS: Final = frozenset(
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
    ]
)

# Path prefixes exempt from kill switch (only admin endpoints)
EXEMPT_PREFIXES: Final = ("/api/admin",)

# Endpoints that should be tracked in the audit log (LLM calls, expensive operations)
AUDIT_ENDPOINTS: Final = (
    "/api/complete",
    "/api/stream",
    "/api/v1/chat/completions",
    "/api/sessions",
    "/api/credentials",
    "/api/api-keys",
)


def is_path_exempt(path: str) -> bool:
    """Check if path is exempt from kill switch checks."""
    return path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES)


def is_internal_request(request: Request) -> bool:
    """Check if request is from agent-hub internal service."""
    return request.headers.get(INTERNAL_SERVICE_HEADER) == settings.internal_service_secret


def should_audit_request(path: str) -> bool:
    """Check if request should be logged to audit trail."""
    return any(path.startswith(ep) for ep in AUDIT_ENDPOINTS)
