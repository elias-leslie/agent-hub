"""SDK example using agent-hub-client package."""

import asyncio

from agent_hub import AsyncAgentHubClient, ImageContent


async def main() -> None:
    """Demonstrate SDK features."""
    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        # Simple completion
        print("=== Simple Completion ===")
        response = await client.complete(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "What is 2 + 2?"}],
        )
        print(f"Response: {response.content}")
        print(f"Tokens: {response.usage.total_tokens}\n")

        # Streaming
        print("=== Streaming ===")
        async for chunk in client.stream_sse(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Count from 1 to 5"}],
        ):
            print(chunk.content, end="", flush=True)
        print("\n")

        # Session management
        print("=== Session Management ===")
        async with client.session(
            project_id="demo",
            provider="claude",
            model="claude-sonnet-4-5",
        ) as session:
            response = await session.complete("My favorite color is blue.")
            print(f"Response 1: {response.content}")

            response = await session.complete("What is my favorite color?")
            print(f"Response 2: {response.content}")

            history = await session.get_history()
            print(f"History: {len(history)} messages\n")

        # Vision example (with placeholder image)
        print("=== Vision API ===")
        # Create an image content block
        image = ImageContent.from_base64(
            # 1x1 red PNG
            data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
            media_type="image/png",
        )
        print(f"ImageContent created: type={image.type}")
        print("(Actual vision call requires valid image data)")


if __name__ == "__main__":
    asyncio.run(main())
