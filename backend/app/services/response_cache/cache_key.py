"""Cache key generation utilities."""

import hashlib
import json

from .constants import CACHE_PREFIX, FALLBACK_PREFIX


def generate_cache_key(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    """
    Generate cache key from request parameters.

    Creates a deterministic hash from all parameters that affect the response.
    """
    key_data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    # Sort keys for deterministic JSON
    key_json = json.dumps(key_data, sort_keys=True)
    # Generate SHA256 hash
    key_hash = hashlib.sha256(key_json.encode()).hexdigest()[:32]
    return f"{CACHE_PREFIX}{key_hash}"


def get_fallback_key(cache_key: str) -> str:
    """Convert primary cache key to fallback key."""
    return cache_key.replace(CACHE_PREFIX, FALLBACK_PREFIX)
