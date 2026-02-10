"""Constants for response caching."""

# Default cache TTL (5 minutes)
DEFAULT_CACHE_TTL = 300

# Stale-if-error TTL for degraded mode (1 hour - use older cached responses when providers down)
STALE_IF_ERROR_TTL = 3600

# Cache key prefix
CACHE_PREFIX = "agent-hub:response:"

# Fallback cache prefix (separate storage for stale-if-error responses)
FALLBACK_PREFIX = "agent-hub:fallback:"
