"""Canonical clarify -> plan -> execute -> review -> QA workflow example."""

import asyncio

from agent_hub import AsyncAgentHubClient

PROJECT_ID = "agent-hub"
WORKING_DIR = "/srv/workspaces/projects/agent-hub"
CURRENT_BRANCH = "task-df826c65/main"


async def main() -> None:
    """Run canonical operator workflow through SDK."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        workflow = await client.workflow(
            project_id=PROJECT_ID,
            shared_context=(
                "Repository: agent-hub\n"
                "Goal: add one canonical operator workflow contract without duplicating routing logic."
            ),
            clarify={
                "task": (
                    "List ambiguities that must be resolved before coding and answer them "
                    "directly when repo already shows truth."
                ),
            },
            plan={
                "task": "Produce execution-ready implementation plan using prior workflow outputs.",
            },
            execute={
                "task": "Implement approved plan in repo using existing orchestration and agent-routing primitives.",
                "execute_tools": True,
                "max_turns": 6,
                "working_dir": WORKING_DIR,
                "current_branch": CURRENT_BRANCH,
            },
            review={
                "task": "Review implementation for concrete bugs, drift from request, and missing verification.",
            },
            qa={
                "task": "Run final QA over full workflow and call out remaining blockers before closeout.",
            },
        )

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
