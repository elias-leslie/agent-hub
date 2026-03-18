"""Orchestration example - multi-agent subagent spawning."""

import asyncio

import httpx

BASE_URL = "http://localhost:8003/api"


async def main() -> None:
    """Run a subagent orchestration."""
    async with httpx.AsyncClient() as client:
        # Spawn a subagent
        response = await client.post(
            f"{BASE_URL}/orchestration/subagent",
            json={
                "prompt": "Analyze this code and suggest improvements",
                "agent_slug": "coder",
                "parent_session_id": None,
            },
            timeout=120.0,
        )
        data = response.json()
        print("Subagent completed")
        print(f"Response: {data.get('content', '')[:200]}...")

        # Run parallel execution
        parallel_response = await client.post(
            f"{BASE_URL}/orchestration/parallel",
            json={
                "tasks": [
                    {"prompt": "Summarize the README", "agent_slug": "observer"},
                    {"prompt": "List the main endpoints", "agent_slug": "observer"},
                ],
            },
            timeout=120.0,
        )
        parallel_data = parallel_response.json()
        print(f"\nParallel results: {len(parallel_data.get('results', []))} tasks completed")


if __name__ == "__main__":
    asyncio.run(main())
