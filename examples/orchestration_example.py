"""Canonical clarify -> plan -> execute -> review -> QA workflow example."""

import asyncio

from agent_hub import AsyncAgentHubClient

PROJECT_ID = "agent-hub"


async def main() -> None:
    """Run the canonical operator workflow through the SDK."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        workflow = await client.workflow(
            project_id=PROJECT_ID,
            shared_context=(
                "Repository: agent-hub\n"
                "Goal: add one canonical operator workflow contract without duplicating routing logic."
            ),
            clarify={
                "task": "List the ambiguities that must be resolved before coding and answer them directly when the codebase already provides the evidence.",
            },
            plan={
                "task": "Produce an execution-ready implementation plan using the clarified scope and prior workflow outputs.",
            },
            execute={
                "task": "Implement the approved plan in the repo, reusing existing orchestration and agent-routing primitives.",
                "execute_tools": True,
                "max_turns": 6,
                "working_dir": "/srv/workspaces/projects/agent-hub",
                "current_branch": "main",
            },
            review={
                "task": "Review the implementation for concrete bugs, drift from the clarified request, and missing verification.",
            },
            qa={
                "task": "Run final QA over the full workflow and call out any remaining blockers before closeout.",
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
