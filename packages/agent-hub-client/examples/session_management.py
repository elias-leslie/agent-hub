#!/usr/bin/env python3
"""Session management example using the Agent Hub Python SDK."""

import asyncio

from agent_hub import AsyncAgentHubClient


async def main() -> None:
    """Demonstrate session management for multi-turn conversations."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        response1 = await client.complete(
            agent_slug="chat",
            project_id="example-project",
            messages=[{"role": "user", "content": "My name is Alice."}],
        )
        print(f"Session: {response1.session_id}")
        print(f"Assistant: {response1.content}")

        response2 = await client.complete(
            agent_slug="chat",
            project_id="example-project",
            session_id=response1.session_id,
            messages=[{"role": "user", "content": "What's my name?"}],
        )
        print(f"Assistant: {response2.content}")

        history = await client.get_session(response1.session_id)
        print(f"\nConversation has {len(history.messages)} messages")


if __name__ == "__main__":
    asyncio.run(main())
