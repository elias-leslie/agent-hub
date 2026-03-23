"""Hatchet worker entrypoint for agent-hub maintenance workflows."""

from __future__ import annotations

from app.worker_runtime import OPS_WORKFLOWS, run_worker_process


def main() -> None:
    run_worker_process("agent-hub-ops-worker", OPS_WORKFLOWS)


if __name__ == "__main__":
    main()
