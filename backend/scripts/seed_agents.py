"""Seed default agents into the database.

Run with: python -m scripts.seed_agents

Uses upsert pattern: creates new agents and updates existing ones.
System prompts live in the DB (Agent.system_prompt) — no persistent prompt files.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Agent
from scripts.seed_agents_data import DEACTIVATE_SLUGS, DEFAULT_AGENTS, UPSERT_FIELDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_agents(db: AsyncSession) -> tuple[int, int]:
    """Seed default agents into database using upsert pattern.

    Returns:
        Tuple of (created_count, updated_count)
    """
    created = 0
    updated = 0

    for agent_data in DEFAULT_AGENTS:
        slug = agent_data["slug"]
        result = await db.execute(select(Agent).where(Agent.slug == slug))
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing agent
            changed = False
            for field in UPSERT_FIELDS:
                if field in agent_data:
                    new_val = agent_data[field]
                    old_val = getattr(existing, field)
                    if new_val != old_val:
                        setattr(existing, field, new_val)
                        changed = True

            # Ensure active
            if not existing.is_active:
                existing.is_active = True
                changed = True

            if changed:
                existing.version += 1
                updated += 1
                logger.info(f"Updated agent: {slug}")
            else:
                logger.info(f"Agent '{slug}' unchanged, skipping")
        else:
            # Create new agent
            agent = Agent(
                slug=slug,
                name=agent_data["name"],
                description=agent_data.get("description"),
                system_prompt=agent_data["system_prompt"],
                primary_model_id=agent_data["primary_model_id"],
                fallback_models=agent_data.get("fallback_models", []),
                escalation_model_id=agent_data.get("escalation_model_id"),
                strategies=agent_data.get("strategies", {}),
                temperature=agent_data.get("temperature", 0.7),
                is_active=True,
                is_coding_agent=agent_data.get("is_coding_agent", False),
                tool_permissions=agent_data.get("tool_permissions"),
                memory_config=agent_data.get("memory_config"),
                version=1,
            )
            db.add(agent)
            created += 1
            logger.info(f"Created agent: {slug}")

    # Deactivate absorbed agents
    for slug in DEACTIVATE_SLUGS:
        result = await db.execute(select(Agent).where(Agent.slug == slug))
        deactivate_agent = result.scalar_one_or_none()
        if deactivate_agent and deactivate_agent.is_active:
            deactivate_agent.is_active = False
            deactivate_agent.version += 1
            logger.info(f"Deactivated agent: {slug}")

    await db.commit()
    return created, updated


async def main() -> None:
    """Run the seed script."""
    db_url = settings.agent_hub_db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        created, updated = await seed_agents(db)
        logger.info(f"Seeded agents: {created} created, {updated} updated")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
