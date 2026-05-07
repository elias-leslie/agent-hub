"""Project and agent type constants.

VALID_PROJECT_IDS are derived dynamically from project_permissions.
Project roots are always derived through the canonical resolver in
app.core.project_roots so there is exactly one root-resolution path.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {
    "claude",
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
# Dynamic project data — derived from project_permissions table
# ---------------------------------------------------------------------------

# Fallback used when DB is unavailable (startup, tests, migrations)
_FALLBACK_PROJECT_IDS: frozenset[str] = frozenset({
    "summitflow",
    "agent-hub",
    "vantage",
    "portfolio-ai",
    "a-term",
    "monkey-fight",
    "persona-sandbox",
    "st-cli",
    "claude-consultation",
    "consult",
    "agent-playground",
})

_cached_project_ids: frozenset[str] | None = None
_cached_roots: dict[str, str] | None = None
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def _resolve_known_roots(project_ids: frozenset[str]) -> dict[str, str]:
    """Resolve project roots from the canonical single-project resolver."""
    from app.core.project_roots import resolve_project_root

    roots: dict[str, str] = {}
    for project_id in project_ids:
        resolved = resolve_project_root(project_id)
        if resolved is not None:
            roots[project_id] = str(resolved)
    return roots


async def refresh_project_cache() -> frozenset[str]:
    """Refresh project IDs cache from project_permissions and derive roots canonically.

    Called on app startup and periodically from async contexts.
    """
    global _cached_project_ids, _cached_roots, _cache_timestamp
    try:
        from sqlalchemy import text

        from app.db import async_session

        async with async_session() as db:
            result = await db.execute(
                text("SELECT project_id FROM project_permissions")
            )
            rows = list(result)
            db_ids = frozenset(row[0] for row in rows)

        if db_ids:
            _cached_project_ids = db_ids
            _cached_roots = _resolve_known_roots(db_ids)
            _cache_timestamp = time.monotonic()
            return db_ids
    except Exception as e:
        logger.debug("Could not refresh project cache from DB: %s", e)

    return _cached_project_ids or _FALLBACK_PROJECT_IDS


# Backward-compatible alias
refresh_project_ids_cache = refresh_project_cache


def get_valid_project_ids() -> frozenset[str]:
    """Get valid project IDs from cache. Falls back to hardcoded set."""
    if _cached_project_ids is not None:
        return _cached_project_ids
    return _FALLBACK_PROJECT_IDS


def get_known_roots() -> dict[str, str]:
    """Get project_id → root_path mapping via the canonical root resolver."""
    if _cached_roots is not None:
        return _cached_roots
    return _resolve_known_roots(_cached_project_ids or _FALLBACK_PROJECT_IDS)


def is_cache_stale() -> bool:
    """Check if the cache needs refreshing."""
    if _cached_project_ids is None:
        return True
    return (time.monotonic() - _cache_timestamp) >= _CACHE_TTL_SECONDS


def invalidate_project_cache() -> None:
    """Force next call to refresh_project_cache() to reload from DB."""
    global _cached_project_ids, _cached_roots, _cache_timestamp
    _cached_project_ids = None
    _cached_roots = None
    _cache_timestamp = 0.0
    from app.core.project_roots import resolve_project_root

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
        return True


VALID_PROJECT_IDS: frozenset[str] = _ProjectIDsProxy()  # type: ignore[assignment]
