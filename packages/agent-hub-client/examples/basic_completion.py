#!/usr/bin/env python3
"""Basic completion example using the Agent Hub Python SDK."""

import asyncio

from agent_hub import AsyncAgentHubClient


async def main() -> None:
    """Demonstrate basic completion."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        # Simple completion
        response = await client.complete(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "What is 2 + 2?"}],
        )

        print(f"Response: {response.content}")
        print(f"Model: {response.model}")
        print(f"Tokens: {response.usage.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())
