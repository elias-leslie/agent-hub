"""Hatchet worker entrypoint.

Registers all workflows and starts the worker process.
Run with: python -m app.worker
"""

from __future__ import annotations

from app.hatchet_app import hatchet
from app.workflows.completion import completion_task
from app.workflows.observation import observation_processing_task
from app.workflows.scheduled import (
    memory_cleanup_task,
    session_cleanup_task,
    tier_optimizer_task,
)
from app.workflows.summary import session_summary_task
from app.workflows.webhooks import webhook_delivery_task


def main() -> None:
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
        ],
    )
    worker.start()


if __name__ == "__main__":
    main()
