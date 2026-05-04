"""Memory settings service — get/update global memory system settings."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import MemorySettings

logger = logging.getLogger(__name__)

# Default values
DEFAULT_ENABLED = True
DEFAULT_BUDGET_ENABLED = True
DEFAULT_TOTAL_BUDGET = 3500
DEFAULT_MAX_MANDATES = 0  # 0 = unlimited
DEFAULT_MAX_GUARDRAILS = 0  # 0 = unlimited
DEFAULT_REFERENCE_INDEX_ENABLED = True  # TOON compressed reference index
DEFAULT_CONTINUITY_ENABLED = True
DEFAULT_CONTINUITY_MAX_SESSIONS = 5
_UNSET = object()


@dataclass
class MemorySettingsDTO:
    """Data transfer object for memory settings."""

    enabled: bool
    budget_enabled: bool
    total_budget: int
    max_mandates: int = 0
    max_guardrails: int = 0
    reference_index_enabled: bool = True
    continuity_enabled: bool = True
    continuity_max_sessions: int = 5
    active_variant: str | None = None


def _defaults_dto() -> MemorySettingsDTO:
    """Return MemorySettingsDTO with all default values."""
    return MemorySettingsDTO(
        enabled=DEFAULT_ENABLED, budget_enabled=DEFAULT_BUDGET_ENABLED,
        total_budget=DEFAULT_TOTAL_BUDGET, max_mandates=DEFAULT_MAX_MANDATES,
        max_guardrails=DEFAULT_MAX_GUARDRAILS,
        reference_index_enabled=DEFAULT_REFERENCE_INDEX_ENABLED,
        continuity_enabled=DEFAULT_CONTINUITY_ENABLED,
        continuity_max_sessions=DEFAULT_CONTINUITY_MAX_SESSIONS,
        active_variant=None,
    )


def _orm_to_dto(s: MemorySettings) -> MemorySettingsDTO:
    """Convert a MemorySettings ORM object to MemorySettingsDTO."""
    return MemorySettingsDTO(
        enabled=s.enabled, budget_enabled=s.budget_enabled,
        total_budget=s.total_budget, max_mandates=s.max_mandates,
        max_guardrails=s.max_guardrails,
        reference_index_enabled=getattr(s, "reference_index_enabled", DEFAULT_REFERENCE_INDEX_ENABLED),
        continuity_enabled=getattr(s, "continuity_enabled", DEFAULT_CONTINUITY_ENABLED),
        continuity_max_sessions=getattr(s, "continuity_max_sessions", DEFAULT_CONTINUITY_MAX_SESSIONS),
        active_variant=getattr(s, "active_variant", None),
    )


async def _fetch_settings(session: AsyncSession) -> MemorySettingsDTO:
    result = await session.execute(select(MemorySettings).where(MemorySettings.id == 1))
    s = result.scalar_one_or_none()
    if s is None:
        logger.warning("No memory settings found, using defaults")
        return _defaults_dto()
    return _orm_to_dto(s)


async def get_memory_settings(db: AsyncSession | None = None) -> MemorySettingsDTO:
    """Get current memory settings (singleton id=1). Returns defaults if not found.

    Args:
        db: Database session (optional — a new session is created if omitted)
    """
    if db is not None:
        return await _fetch_settings(db)
    async with async_session() as session:
        return await _fetch_settings(session)
    return _defaults_dto()


def _create_settings_row(updates: dict[str, object]) -> MemorySettings:
    """Build a new MemorySettings row, filling missing values from defaults."""
    d = _defaults_dto()
    return MemorySettings(
        id=1,
        enabled=updates["enabled"] if updates["enabled"] is not None else d.enabled,
        budget_enabled=updates["budget_enabled"] if updates["budget_enabled"] is not None else d.budget_enabled,
        total_budget=updates["total_budget"] if updates["total_budget"] is not None else d.total_budget,
        max_mandates=updates["max_mandates"] if updates["max_mandates"] is not None else d.max_mandates,
        max_guardrails=updates["max_guardrails"] if updates["max_guardrails"] is not None else d.max_guardrails,
        reference_index_enabled=updates["reference_index_enabled"] if updates["reference_index_enabled"] is not None else d.reference_index_enabled,
        continuity_enabled=updates["continuity_enabled"] if updates["continuity_enabled"] is not None else d.continuity_enabled,
        continuity_max_sessions=updates["continuity_max_sessions"] if updates["continuity_max_sessions"] is not None else d.continuity_max_sessions,
        active_variant=d.active_variant
        if updates["active_variant"] is _UNSET
        else updates["active_variant"],
    )


def _should_apply_update(value: object) -> bool:
    """Return whether a partial settings value should be applied."""
    return value is not None and value is not _UNSET


async def update_memory_settings(
    db: AsyncSession,
    *,
    enabled: bool | None = None,
    budget_enabled: bool | None = None,
    total_budget: int | None = None,
    max_mandates: int | None = None,
    max_guardrails: int | None = None,
    reference_index_enabled: bool | None = None,
    continuity_enabled: bool | None = None,
    continuity_max_sessions: int | None = None,
    active_variant: str | None | object = _UNSET,
) -> MemorySettingsDTO:
    """Upsert memory settings (creates the row if it doesn't exist).

    All keyword arguments are optional; only provided values are applied.
    """
    updates: dict[str, object] = dict(
        enabled=enabled, budget_enabled=budget_enabled, total_budget=total_budget,
        max_mandates=max_mandates, max_guardrails=max_guardrails,
        reference_index_enabled=reference_index_enabled,
        continuity_enabled=continuity_enabled, continuity_max_sessions=continuity_max_sessions,
        active_variant=active_variant,
    )
    result = await db.execute(select(MemorySettings).where(MemorySettings.id == 1))
    settings = result.scalar_one_or_none()

    if settings is None:
        settings = _create_settings_row(updates)
        db.add(settings)
    else:
        for field, value in updates.items():
            if _should_apply_update(value):
                setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)
    logger.info(
        "Updated memory settings: enabled=%s, max_mandates=%d, max_guardrails=%d, ref_index=%s, continuity=%s",
        settings.enabled, settings.max_mandates, settings.max_guardrails,
        getattr(settings, "reference_index_enabled", True),
        getattr(settings, "continuity_enabled", True),
    )
    return _orm_to_dto(settings)


async def set_active_memory_variant(active_variant: str | None) -> MemorySettingsDTO:
    """Set or clear the globally active memory variant."""
    async with async_session() as session:
        return await update_memory_settings(session, active_variant=active_variant)
    return _defaults_dto()
