#!/usr/bin/env python3
"""Profile extended thinking response times."""

import asyncio
import time

from app.adapters.base import Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter


async def test_extended_thinking():
    """Test response times with extended thinking enabled."""
    print("Extended Thinking Response Time Test")
    print("="*60)

    # Complex reasoning prompt that benefits from thinking
    prompt = """A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball.
How much does the ball cost? Think through this very carefully and show your reasoning."""

    thinking_levels = ["low", "high"]

    # Test Claude
    print("\nClaude Sonnet 4.5 with Extended Thinking:")
    print("-"*60)
    try:
        claude = ClaudeAdapter()
        for level in thinking_levels:
            start = time.time()
            result = await claude.complete(
                messages=[Message(role="user", content=prompt)],
                model="claude-sonnet-4-5",
                max_tokens=2000,
                thinking_level=level,
            )
            elapsed = time.time() - start

            thinking_chars = len(result.thinking_content) if result.thinking_content else 0
            print(f"\n{level.upper()} thinking:")
            print(f"  Time: {elapsed:.1f}s ({int(elapsed*1000)}ms)")
            print(f"  Output: {result.output_tokens} tokens, {len(result.content)} chars")
            print(f"  Thinking: {result.thinking_tokens or 0} tokens, {thinking_chars} chars")

            await asyncio.sleep(2)
    except Exception as e:
        print(f"  ✗ Error: {e}")

    # Test Gemini
    print("\n\nGemini 3 Flash with Extended Thinking:")
    print("-"*60)
    try:
        gemini = GeminiAdapter()
        for level in thinking_levels:
            start = time.time()
            result = await gemini.complete(
                messages=[Message(role="user", content=prompt)],
                model="gemini-3-flash-preview",
                max_tokens=2000,
                thinking_level=level,
            )
            elapsed = time.time() - start

            print(f"\n{level.upper()} thinking:")
            print(f"  Time: {elapsed:.1f}s ({int(elapsed*1000)}ms)")
            print(f"  Output: {result.output_tokens} tokens, {len(result.content)} chars")

            await asyncio.sleep(2)
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print("\n" + "="*60)
    print("Note: Extended thinking can add 10-30s to response time")
    print("Current plan: 120s timeout should handle extended thinking")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_extended_thinking())
