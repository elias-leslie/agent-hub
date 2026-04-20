"""Canonical clarify -> plan -> execute -> review -> QA workflow example."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

DEFAULT_PROJECT_ID = "agent-hub"
DEFAULT_BASE_URL = "http://localhost:8003"
DEFAULT_WORKING_DIR = "/srv/workspaces/projects/agent-hub"


def build_workflow_request_payload(
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    working_dir: str = DEFAULT_WORKING_DIR,
    current_branch: str | None = None,
) -> dict[str, Any]:
    execute_stage: dict[str, Any] = {
        "task": "Implement approved plan in repo using existing orchestration and agent-routing primitives.",
        "execute_tools": True,
        "max_turns": 6,
        "working_dir": working_dir,
    }
    if current_branch:
        execute_stage["current_branch"] = current_branch

    return {
        "project_id": project_id,
        "shared_context": (
            "Repository: agent-hub\n"
            "Goal: add one canonical operator workflow contract without duplicating routing logic."
        ),
        "clarify": {
            "task": (
                "List ambiguities that must be resolved before coding and answer them "
                "directly when repo already shows truth."
            ),
        },
        "plan": {
            "task": "Produce execution-ready implementation plan using prior workflow outputs.",
        },
        "execute": execute_stage,
        "review": {
            "task": "Review implementation for concrete bugs, drift from request, and missing verification.",
        },
        "qa": {
            "task": "Run final QA over full workflow and call out remaining blockers before closeout.",
        },
    }


async def main() -> None:
    """Run canonical operator workflow through SDK."""
    payload = build_workflow_request_payload(
        project_id=os.getenv("AGENT_HUB_WORKFLOW_PROJECT_ID", DEFAULT_PROJECT_ID),
        working_dir=os.getenv("AGENT_HUB_WORKFLOW_WORKING_DIR", DEFAULT_WORKING_DIR),
        current_branch=os.getenv("AGENT_HUB_WORKFLOW_BRANCH") or None,
    )
    if os.getenv("AGENT_HUB_WORKFLOW_DRY_RUN") == "1":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    from agent_hub import AsyncAgentHubClient

    async with AsyncAgentHubClient(base_url=os.getenv("AGENT_HUB_BASE_URL", DEFAULT_BASE_URL)) as client:
        workflow = await client.workflow(**payload)

    print(f"Workflow status: {workflow['status']}")
    for stage in workflow["stages"]:
        preview = stage["content"].strip().replace("\n", " ")
        print(f"\n[{stage['stage']}] agent={stage.get('agent_used')}")
        print(preview[:240] + ("..." if len(preview) > 240 else ""))

    print(
        "\nTotals:",
        f"input={workflow['total_input_tokens']}",
        f"output={workflow['total_output_tokens']}",
    )


if __name__ == "__main__":
    asyncio.run(main())
