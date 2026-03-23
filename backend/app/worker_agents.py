"""Hatchet worker entrypoint for long-lived agent execution."""

from __future__ import annotations

from app.worker_runtime import AGENT_WORKFLOWS, run_worker_process


def main() -> None:
    run_worker_process("agent-hub-agent-worker", AGENT_WORKFLOWS)


if __name__ == "__main__":
    main()
