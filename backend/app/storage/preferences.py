"""Storage functions for user preferences."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserPreferences


async def get_preferences_async(
    db: AsyncSession,
    user_id: str,
) -> UserPreferences | None:
    """Get user preferences by user ID."""
    result = await db.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
    return result.scalar_one_or_none()


async def upsert_preferences_async(
    db: AsyncSession,
    user_id: str,
    verbosity: str | None = None,
    tone: str | None = None,
    default_model: str | None = None,
) -> UserPreferences:
    """Create or update user preferences."""
    existing = await get_preferences_async(db, user_id)

    if existing:
        # Update existing preferences
        if verbosity is not None:
            existing.verbosity = verbosity
        if tone is not None:
            existing.tone = tone
        if default_model is not None:
            existing.default_model = default_model
        await db.commit()
        await db.refresh(existing)
        return existing

    # Create new preferences
    prefs = UserPreferences(
        user_id=user_id,
        verbosity=verbosity or "normal",
        tone=tone or "professional",
        default_model=default_model or "claude-sonnet-4-5",
    )
    db.add(prefs)
    await db.commit()
    await db.refresh(prefs)
    return prefs
