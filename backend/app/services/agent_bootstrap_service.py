"""Bootstrap default agent records for fresh databases."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_agents import seed_agents


async def bootstrap_default_agents(db: AsyncSession) -> int:
    """Insert any missing default agents from the checked-in seed set."""
    return await seed_agents(db)
