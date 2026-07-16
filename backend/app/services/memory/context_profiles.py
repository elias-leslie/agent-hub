"""Consumer-specific progressive-context rendering profiles."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.services.memory.applicability import normalize_context_identifier

# Memory tag that signals a memory should render at full detail when delivered
# to any startup consumer. Tag string kept as `codex_startup_full` to avoid
# rewriting existing memory tags during the unified-startup migration.
AGENT_STARTUP_FULL_TAG = "codex_startup_full"
CODEX_STARTUP_FULL_TAG = AGENT_STARTUP_FULL_TAG


class MemoryConsumerProfile(StrEnum):
    """Supported delivery profiles for injected memory context."""

    AGENT_RUNTIME = "agent_runtime"
    AGENT_PREVIEW = "agent_preview"
    AGENT_GENERAL = "agent_general"
    AGENT_VISUAL = "agent_visual"
    AGENT_CODING = "agent_coding"
    AGENT_OPERATOR = "agent_operator"
    AGENT_PROMPTOPS = "agent_promptops"
    AGENT_STARTUP = "agent_startup"


# Legacy per-CLI startup profile names that all resolve to AGENT_STARTUP.
_LEGACY_STARTUP_ALIASES: frozenset[str] = frozenset(
    {"claude_session_start", "codex_startup", "gemini_startup"}
)


_PROFILE_POLICY_LIMITS: dict[MemoryConsumerProfile, tuple[int, int]] = {
    MemoryConsumerProfile.AGENT_PREVIEW: (8, 2),
    MemoryConsumerProfile.AGENT_GENERAL: (6, 2),
    MemoryConsumerProfile.AGENT_VISUAL: (6, 2),
    MemoryConsumerProfile.AGENT_CODING: (16, 4),
    MemoryConsumerProfile.AGENT_OPERATOR: (20, 6),
    MemoryConsumerProfile.AGENT_PROMPTOPS: (14, 4),
    # Keep in sync with the runtime_context_profile_policies DB row (40/10) so a
    # missing row doesn't silently shrink startup context.
    MemoryConsumerProfile.AGENT_STARTUP: (40, 10),
}
_PROFILE_QUERY_REFERENCE_DEFAULTS: dict[MemoryConsumerProfile, bool] = {
    MemoryConsumerProfile.AGENT_PREVIEW: False,
    MemoryConsumerProfile.AGENT_GENERAL: False,
    MemoryConsumerProfile.AGENT_VISUAL: False,
    MemoryConsumerProfile.AGENT_CODING: True,
    MemoryConsumerProfile.AGENT_OPERATOR: True,
    MemoryConsumerProfile.AGENT_PROMPTOPS: True,
    MemoryConsumerProfile.AGENT_STARTUP: False,
}


def resolve_consumer_profile(consumer_profile: str | None) -> MemoryConsumerProfile:
    """Normalize caller-provided profile names to a known profile."""
    normalized = normalize_context_identifier(consumer_profile)
    if not normalized:
        return MemoryConsumerProfile.AGENT_RUNTIME
    if normalized in _LEGACY_STARTUP_ALIASES:
        return MemoryConsumerProfile.AGENT_STARTUP
    try:
        return MemoryConsumerProfile(normalized)
    except ValueError:
        return MemoryConsumerProfile.AGENT_RUNTIME


def full_render_tags_for_profile(consumer_profile: str | None) -> set[str]:
    """Return memory tags that should render at full detail for a profile."""
    profile = resolve_consumer_profile(consumer_profile)
    if profile == MemoryConsumerProfile.AGENT_STARTUP:
        return {AGENT_STARTUP_FULL_TAG}
    return set()


def priority_tags_for_profile(consumer_profile: str | None) -> set[str]:
    """Return memory tags that should be surfaced first for a profile."""
    return full_render_tags_for_profile(consumer_profile)


def policy_limits_for_profile(consumer_profile: str | None) -> tuple[int, int]:
    """Return mandate/guardrail caps from the Python fallback dict.

    Prefer `resolve_policy_limits` (async) when DB access is available — it
    layers per-agent memory_config overrides on top of DB-backed per-profile
    defaults, falling back to this dict only when the row is missing.
    """
    profile = resolve_consumer_profile(consumer_profile)
    return _PROFILE_POLICY_LIMITS.get(profile, (0, 0))


# In-process cache for DB-backed per-profile policy rows. Keyed by
# consumer_profile value; tuple is (mandate, guardrail, reference) where each
# element is an int|None (None = uncapped). Invalidated by upsert path.
_POLICY_CACHE: dict[str, tuple[int | None, int | None, int | None]] | None = None


def invalidate_policy_cache() -> None:
    """Clear the in-process policy cache (called from the PUT endpoint)."""
    global _POLICY_CACHE
    _POLICY_CACHE = None


async def _load_policy_cache(db: AsyncSession) -> dict[str, tuple[int | None, int | None, int | None]]:
    # Imported lazily to avoid circular import at module load.
    from app.models.runtime_context import RuntimeContextProfilePolicy

    rows = (await db.execute(select(RuntimeContextProfilePolicy))).scalars().all()
    return {
        row.consumer_profile: (row.mandate_limit, row.guardrail_limit, row.reference_limit)
        for row in rows
    }


async def _ensure_policy_cache(db: AsyncSession | None) -> dict[str, tuple[int | None, int | None, int | None]]:
    global _POLICY_CACHE
    if _POLICY_CACHE is not None:
        return _POLICY_CACHE
    if db is not None:
        _POLICY_CACHE = await _load_policy_cache(db)
        return _POLICY_CACHE
    async with async_session() as session:
        _POLICY_CACHE = await _load_policy_cache(session)
        return _POLICY_CACHE


def _coerce_int_limit(value: Any, fallback: int) -> int:
    """Coerce a memory_config override value to an int cap (0 = uncapped).

    Accepts int (including 0 = uncapped) or None. Anything else falls back to
    the resolved profile default.
    """
    if value is None:
        return fallback
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return max(value, 0)
    return fallback


async def resolve_policy_limits(
    consumer_profile: str | None,
    memory_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> tuple[int, int, int]:
    """Resolve effective (mandate, guardrail, reference) caps.

    Resolution chain: per-agent `memory_config` (mandate_limit, guardrail_limit,
    reference_limit) → DB profile policy row → Python fallback dict. Returned
    integers use 0 = uncapped semantics so callers can pass directly to
    `_limit_policy_item_count`.
    """
    profile = resolve_consumer_profile(consumer_profile)
    py_mandate, py_guardrail = _PROFILE_POLICY_LIMITS.get(profile, (0, 0))
    py_reference = 0  # No Python-fallback reference cap today.

    cache = await _ensure_policy_cache(db)
    db_mandate, db_guardrail, db_reference = cache.get(profile.value, (None, None, None))
    mandate_default = py_mandate if db_mandate is None else db_mandate
    guardrail_default = py_guardrail if db_guardrail is None else db_guardrail
    reference_default = py_reference if db_reference is None else db_reference

    if memory_config is None:
        return mandate_default, guardrail_default, reference_default

    mandate = _coerce_int_limit(memory_config.get("mandate_limit"), mandate_default)
    guardrail = _coerce_int_limit(memory_config.get("guardrail_limit"), guardrail_default)
    reference = _coerce_int_limit(memory_config.get("reference_limit"), reference_default)
    return mandate, guardrail, reference


def summarize_policies_for_profile(consumer_profile: str | None) -> bool:
    """Return True when mandates/guardrails should render as compact summaries."""
    profile = resolve_consumer_profile(consumer_profile)
    return profile in _PROFILE_POLICY_LIMITS


def startup_limits_for_profile(consumer_profile: str | None) -> tuple[int, int]:
    """Backward-compatible alias for older callers/tests."""
    return policy_limits_for_profile(consumer_profile)


def query_reference_selection_default_for_profile(consumer_profile: str | None) -> bool | None:
    """Return default semantic-reference behavior for a consumer profile.

    `None` means caller should use legacy fallback behavior.
    """
    profile = resolve_consumer_profile(consumer_profile)
    return _PROFILE_QUERY_REFERENCE_DEFAULTS.get(profile)
