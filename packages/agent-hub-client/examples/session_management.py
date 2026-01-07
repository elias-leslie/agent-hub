#!/usr/bin/env python3
"""Session management example using the Agent Hub Python SDK."""

import asyncio

from agent_hub import AsyncAgentHubClient


async def main() -> None:
    """Demonstrate session management for multi-turn conversations."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        # Create a new session
        async with client.session(
            project_id="example-project",
            provider="claude",
            model="claude-sonnet-4-5",
        ) as session:
            print(f"Created session: {session.session_id}")

            # First message
            response1 = await session.complete("My name is Alice.")
            print(f"Assistant: {response1.content}")

            # Follow-up (session remembers context)
            response2 = await session.complete("What's my name?")
            print(f"Assistant: {response2.content}")

            # Get conversation history from server
            history = await session.get_history()
            print(f"\nConversation has {len(history)} messages")

        # Resume session later by ID
        print(f"\nResuming session {session.session_id}...")
        async with client.session(
            project_id="example-project",
            provider="claude",
            model="claude-sonnet-4-5",
            session_id=session.session_id,
        ) as resumed:
            history = await resumed.get_history()
            print(f"Loaded {len(history)} messages from previous session")


if __name__ == "__main__":
    asyncio.run(main())
