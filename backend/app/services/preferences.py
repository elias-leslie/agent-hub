"""User preferences service."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import UserPreference
from app.services.model_selector import QualityPreference

logger = logging.getLogger(__name__)


async def get_global_tier_preference(db: AsyncSession | None = None) -> QualityPreference:
    """Get global tier preference from database.

    Args:
        db: Database session (optional, returns default if not provided)

    Returns:
        QualityPreference enum value (defaults to STANDARD)
    """
    if not db:
        return QualityPreference.STANDARD

    try:
        result = await db.execute(
            select(UserPreference).where(UserPreference.key == "model_tier_preference")
        )
        pref = result.scalar_one_or_none()

        if pref:
            return QualityPreference(pref.value)
    except Exception as e:
        logger.warning(f"Failed to load tier preference from database: {e}")

    return QualityPreference.STANDARD


def resolve_tier_preference(
    request_preference: str | None,
    db_preference: QualityPreference | None = None,
) -> QualityPreference:
    """Resolve tier preference with fallback order: request > global > default.

    Args:
        request_preference: Preference from request (optional)
        db_preference: Global preference from database (optional)

    Returns:
        Resolved QualityPreference
    """
    # Priority 1: Request parameter
    if request_preference:
        try:
            return QualityPreference(request_preference)
        except ValueError:
            logger.warning(f"Invalid tier preference in request: {request_preference}")

    # Priority 2: Global preference from database
    if db_preference:
        return db_preference

    # Priority 3: Default to STANDARD
    return QualityPreference.STANDARD
