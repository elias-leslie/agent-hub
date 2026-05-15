"""Shared Hatchet worker runtime helpers for agent-hub."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from typing import Any

from app.hatchet_app import hatchet
from app.worker_diagnostics import install_asyncio_task_dump_signal
from app.workflows.completion import completion_task
from app.workflows.model_sync import model_enrichment_sync_task
from app.workflows.observation import observation_processing_task
from app.workflows.persona_heartbeat import persona_heartbeat_task
from app.workflows.persona_scheduler import persona_scheduler_task
from app.workflows.persona_wake import agent_wake_task
from app.workflows.scheduled import (
    data_retention_task,
    feedback_cleanup_task,
    memory_cleanup_task,
    memory_governance_task,
    session_cleanup_task,
    tier_optimizer_task,
)
from app.workflows.session_reaper import session_reaper_task
from app.workflows.summary import session_summary_task
from app.workflows.webhooks import webhook_delivery_task

logger = logging.getLogger(__name__)

WorkflowDef = Any

AGENT_WORKFLOWS: tuple[WorkflowDef, ...] = (
    completion_task,
    persona_heartbeat_task,
    agent_wake_task,
)

OPS_WORKFLOWS: tuple[WorkflowDef, ...] = (
    persona_scheduler_task,
    session_cleanup_task,
    tier_optimizer_task,
    memory_cleanup_task,
    memory_governance_task,
    feedback_cleanup_task,
    data_retention_task,
    webhook_delivery_task,
    session_summary_task,
    observation_processing_task,
    model_enrichment_sync_task,
    session_reaper_task,
)

ALL_WORKFLOWS: tuple[WorkflowDef, ...] = OPS_WORKFLOWS + AGENT_WORKFLOWS


async def init_worker_credentials() -> None:
    """Load DB credentials into the singleton cache for worker processes."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.config import settings
    from app.services.credential_manager import get_credential_manager

    db_url = settings.agent_hub_db_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        cm = get_credential_manager()
        loaded = await cm.load_with_retry(
            lambda: AsyncSession(engine, expire_on_commit=False)
        )
        logger.info("Worker: loaded %d credentials", loaded)
    finally:
        await engine.dispose()


def run_worker_process(worker_name: str, workflows: Sequence[WorkflowDef]) -> None:
    """Start a Hatchet worker process for the provided workflow set."""
    asyncio.run(init_worker_credentials())

    worker = hatchet.worker(worker_name, workflows=list(workflows))
    worker._setup_loop()

    if not worker.loop:
        raise RuntimeError("event loop not set, cannot start worker")

    install_asyncio_task_dump_signal(worker.loop)

    asyncio.run_coroutine_threadsafe(worker._aio_start(), worker.loop)
    worker.loop.run_forever()

    if worker.handle_kill:
        sys.exit(0)
