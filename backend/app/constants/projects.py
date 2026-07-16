"""Project and agent type constants backed by the canonical ``st`` registry."""

from __future__ import annotations

import time

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {
    "cloudflare",
    "codex",
    "deepseek",
    "gemini",
    "kimi-code",
    "local",
    "minimax",
    "moonshot",
    "nvidia",
    "openai",
    "openrouter",
    "xai",
    "zhipu",
}

# ---------------------------------------------------------------------------
# Dynamic project identity — derived only from the SummitFlow project registry
# ---------------------------------------------------------------------------

_cached_project_ids: frozenset[str] | None = None
_cached_roots: dict[str, str] | None = None
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


async def refresh_project_cache() -> frozenset[str]:
    """Refresh project identity from the canonical ``st projects`` registry."""
    global _cached_project_ids, _cached_roots, _cache_timestamp
    from app.core.project_roots import get_registered_project_roots

    roots = await get_registered_project_roots(refresh=True)
    _cached_roots = dict(roots)
    _cached_project_ids = frozenset(roots)
    _cache_timestamp = time.monotonic()
    return _cached_project_ids


# Backward-compatible alias
refresh_project_ids_cache = refresh_project_cache


def get_valid_project_ids() -> frozenset[str]:
    """Return the most recently loaded canonical registry identities."""
    return _cached_project_ids or frozenset()


def get_known_roots() -> dict[str, str]:
    """Return the most recently loaded canonical project-root mapping."""
    return dict(_cached_roots or {})


def is_cache_stale() -> bool:
    """Check if the cache needs refreshing."""
    if _cached_project_ids is None:
        return True
    return (time.monotonic() - _cache_timestamp) >= _CACHE_TTL_SECONDS


async def validate_project_id(project_id: str) -> None:
    """Validate an explicit project ID against the canonical registry cache."""
    if is_cache_stale():
        await refresh_project_cache()
    valid_project_ids = get_valid_project_ids()
    if project_id not in valid_project_ids:
        raise ValueError(
            f"Unknown project_id '{project_id}'. "
            f"Valid projects: {sorted(valid_project_ids)}"
        )


def invalidate_project_cache() -> None:
    """Force the next validation to reload the canonical project registry."""
    global _cached_project_ids, _cached_roots, _cache_timestamp
    _cached_project_ids = None
    _cached_roots = None
    _cache_timestamp = 0.0
    from app.core.project_roots import (
        invalidate_registered_project_roots,
        resolve_project_root,
    )

    invalidate_registered_project_roots()
    resolve_project_root.cache_clear()


# Backward-compatible module-level constant — now a lazy proxy.
# Callers use `project_id in VALID_PROJECT_IDS` and `sorted(VALID_PROJECT_IDS)`.


class _ProjectIDsProxy:
    """Proxy that looks like a frozenset but delegates to get_valid_project_ids()."""

    def __contains__(self, item: object) -> bool:
        return item in get_valid_project_ids()

    def __iter__(self):
        return iter(get_valid_project_ids())

    def __len__(self) -> int:
        return len(get_valid_project_ids())

    def __repr__(self) -> str:
        return repr(get_valid_project_ids())

    def __bool__(self) -> bool:
        return bool(get_valid_project_ids())


VALID_PROJECT_IDS: frozenset[str] = _ProjectIDsProxy()  # type: ignore[assignment]
