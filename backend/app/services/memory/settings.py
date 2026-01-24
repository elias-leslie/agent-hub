"""Memory settings service.

Provides functions to get and update global memory system settings,
including token budget limits and enable/disable toggle.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import MemorySettings

logger = logging.getLogger(__name__)

# Default values
DEFAULT_ENABLED = True
DEFAULT_TOTAL_BUDGET = 2000


@dataclass
class MemorySettingsDTO:
    """Data transfer object for memory settings."""

    enabled: bool
    total_budget: int


async def get_memory_settings(db: AsyncSession | None = None) -> MemorySettingsDTO:
    """Get current memory settings.

    Uses singleton pattern - always reads id=1 row.
    If no settings exist, returns defaults.

    Args:
        db: Database session (optional - will create one if not provided)

    Returns:
        MemorySettingsDTO with current settings
    """
    async def _get(session: AsyncSession) -> MemorySettingsDTO:
        result = await session.execute(
            select(MemorySettings).where(MemorySettings.id == 1)
        )
        settings = result.scalar_one_or_none()

        if settings is None:
            logger.warning("No memory settings found, using defaults")
            return MemorySettingsDTO(
                enabled=DEFAULT_ENABLED,
                total_budget=DEFAULT_TOTAL_BUDGET,
            )

        return MemorySettingsDTO(
            enabled=settings.enabled,
            total_budget=settings.total_budget,
        )

    if db is not None:
        return await _get(db)

    # Create a new session if one wasn't provided
    async for session in get_db():
        return await _get(session)

    # Fallback to defaults if we can't get a session
    return MemorySettingsDTO(
        enabled=DEFAULT_ENABLED,
        total_budget=DEFAULT_TOTAL_BUDGET,
    )


async def update_memory_settings(
    db: AsyncSession,
    *,
    enabled: bool | None = None,
    total_budget: int | None = None,
) -> MemorySettingsDTO:
    """Update memory settings.

    Uses upsert pattern - creates settings if they don't exist.

    Args:
        db: Database session
        enabled: Whether memory injection is enabled (optional)
        total_budget: Token budget for context injection (optional)

    Returns:
        Updated MemorySettingsDTO
    """
    result = await db.execute(
        select(MemorySettings).where(MemorySettings.id == 1)
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        # Create default settings
        settings = MemorySettings(
            id=1,
            enabled=enabled if enabled is not None else DEFAULT_ENABLED,
            total_budget=total_budget if total_budget is not None else DEFAULT_TOTAL_BUDGET,
        )
        db.add(settings)
    else:
        # Update existing settings
        if enabled is not None:
            settings.enabled = enabled
        if total_budget is not None:
            settings.total_budget = total_budget

    await db.commit()
    await db.refresh(settings)

    logger.info(
        "Updated memory settings: enabled=%s, total_budget=%d",
        settings.enabled,
        settings.total_budget,
    )

    return MemorySettingsDTO(
        enabled=settings.enabled,
        total_budget=settings.total_budget,
    )
