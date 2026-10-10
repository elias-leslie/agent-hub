"""Shared Hatchet worker runtime helpers for agent-hub."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from typing import Any

from app.hatchet_app import hatchet
from app.services.tools.command_guard import warm_shared_command_guard
from app.worker_diagnostics import install_asyncio_task_dump_signal
from app.workflows.automation_clock import automation_clock_task
from app.workflows.completion import completion_task
from app.workflows.model_sync import model_enrichment_sync_task
from app.workflows.observation import observation_processing_task
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

logger = logging.getLogger(__name__)

WorkflowDef = Any

AGENT_WORKFLOWS: tuple[WorkflowDef, ...] = (
    completion_task,
    agent_wake_task,
)

OPS_WORKFLOWS: tuple[WorkflowDef, ...] = (
    automation_clock_task,
    session_cleanup_task,
    tier_optimizer_task,
    memory_cleanup_task,
    memory_governance_task,
    feedback_cleanup_task,
    data_retention_task,
    session_summary_task,
    observation_processing_task,
    model_enrichment_sync_task,
    session_reaper_task,
)

ALL_WORKFLOWS: tuple[WorkflowDef, ...] = OPS_WORKFLOWS + AGENT_WORKFLOWS


async def init_worker_credentials() -> None:
    """Load credentials and the canonical DB model catalog for worker processes."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.config import settings
    from app.services.credential_manager import get_credential_manager
    from app.services.model_catalog_service import refresh_runtime_model_catalog

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
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await refresh_runtime_model_catalog(db)
    finally:
        await engine.dispose()


def run_worker_process(worker_name: str, workflows: Sequence[WorkflowDef]) -> None:
    """Start a Hatchet worker process for the provided workflow set."""
    asyncio.run(init_worker_credentials())
    # Before the worker loop starts: sync tool code reads these caches.
    warm_shared_command_guard()

    worker = hatchet.worker(worker_name, workflows=list(workflows))
    worker._setup_loop()

    if not worker.loop:
        raise RuntimeError("event loop not set, cannot start worker")

    install_asyncio_task_dump_signal(worker.loop)

    asyncio.run_coroutine_threadsafe(worker._aio_start(), worker.loop)
    worker.loop.run_forever()

    if worker.handle_kill:
        sys.exit(0)
