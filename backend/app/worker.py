"""Hatchet worker entrypoint for the combined compatibility worker.

Registers all workflows and starts the worker process.
Run with: python -m app.worker
"""

from __future__ import annotations

from app.worker_runtime import ALL_WORKFLOWS, run_worker_process


def main() -> None:
    run_worker_process("agent-hub-worker", ALL_WORKFLOWS)


if __name__ == "__main__":
    main()
