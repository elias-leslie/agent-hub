"""Secret generation and verification utilities for client authentication."""

import hashlib
import secrets
from time import monotonic

import bcrypt

# Client secret prefix for Agent Hub clients
SECRET_PREFIX = "ahc_"

# Verification cache: maps (client_id, secret_hash, secret_digest) -> (valid, timestamp)
# Using a dict with TTL instead of lru_cache for time-based expiry
_verification_cache: dict[str, tuple[bool, float]] = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes (internal service-to-service)


def generate_client_secret() -> tuple[str, str, str]:
    """Generate a new client secret.

    Returns:
        Tuple of (full_secret, secret_hash, secret_prefix)
        - full_secret: Show once to user (ahc_ + 40 random chars)
        - secret_hash: bcrypt hash for storage
        - secret_prefix: For display (ahc_ + first 8 chars)
    """
    random_part = secrets.token_urlsafe(30)  # ~40 chars
    full_secret = f"{SECRET_PREFIX}{random_part}"
    secret_hash = bcrypt.hashpw(full_secret.encode(), bcrypt.gensalt()).decode()
    secret_prefix = f"{SECRET_PREFIX}{random_part[:8]}"
    return full_secret, secret_hash, secret_prefix


def _compute_cache_key(client_id: str, secret_hash: str) -> str:
    """Compute cache key from client_id and secret_hash.

    The secret_hash uniquely identifies the secret — no need to include
    the plaintext secret in the key derivation.
    """
    combined = f"{client_id}:{secret_hash}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def verify_secret(secret: str, secret_hash: str, client_id: str | None = None) -> bool:
    """Verify a secret against its bcrypt hash.

    Uses in-memory cache to avoid repeated bcrypt verification (190ms each).
    Cache key is derived from hash of inputs, not plaintext secret.

    Args:
        secret: The secret to verify
        secret_hash: The bcrypt hash from database
        client_id: Optional client ID for cache key (improves cache hit rate)
    """
    cache_key = _compute_cache_key(client_id or "", secret_hash)
    now = monotonic()

    if cache_key in _verification_cache:
        valid, timestamp = _verification_cache[cache_key]
        if now - timestamp < _CACHE_TTL_SECONDS:
            return valid
        del _verification_cache[cache_key]

    try:
        valid = bcrypt.checkpw(secret.encode(), secret_hash.encode())
    except Exception:
        valid = False

    _verification_cache[cache_key] = (valid, now)

    if len(_verification_cache) > 1000:
        _cleanup_cache()

    return valid


def _cleanup_cache() -> None:
    """Remove expired entries from verification cache."""
    now = monotonic()
    expired = [k for k, (_, ts) in _verification_cache.items() if now - ts >= _CACHE_TTL_SECONDS]
    for k in expired:
        del _verification_cache[k]
