"""Hatchet worker entrypoint.

Registers all workflows and starts the worker process.
Run with: python -m app.worker
"""

from __future__ import annotations

import asyncio
import logging

from app.hatchet_app import hatchet
from app.workflows.completion import completion_task
from app.workflows.observation import observation_processing_task
from app.workflows.persona_heartbeat import persona_heartbeat_task
from app.workflows.persona_wake import agent_wake_task
from app.workflows.scheduled import (
    memory_cleanup_task,
    session_cleanup_task,
    tier_optimizer_task,
)
from app.workflows.summary import session_summary_task
from app.workflows.webhooks import webhook_delivery_task

logger = logging.getLogger(__name__)


async def _init_credentials() -> None:
    """Load DB credentials into the singleton cache.

    The worker is a separate process from FastAPI, so ``main.py:lifespan()``
    never runs here.  Without this, every ``cm.is_initialized`` check returns
    False and adapters fall back to env-var keys (which may be empty since
    commit bc10294 moved Gemini keys to DB).

    Uses a disposable engine to avoid polluting the lru_cache'd pool with
    connections bound to this (temporary) event loop — Hatchet creates its
    own loop, and reusing asyncpg connections across loops causes
    "attached to a different loop" errors.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.config import settings
    from app.services.credential_manager import get_credential_manager

    db_url = settings.agent_hub_db_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            cm = get_credential_manager()
            loaded = await cm.load(db)
            logger.info("Worker: loaded %d credentials", loaded)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_init_credentials())

    worker = hatchet.worker(
        "agent-hub-worker",
        workflows=[
            session_cleanup_task,
            tier_optimizer_task,
            memory_cleanup_task,
            webhook_delivery_task,
            session_summary_task,
            observation_processing_task,
            completion_task,
            persona_heartbeat_task,
            agent_wake_task,
        ],
    )
    worker.start()


if __name__ == "__main__":
    main()
