#!/usr/bin/env python3
"""Profile adapter response times to validate timeout values."""

import asyncio
import time
import statistics
from typing import Any

from app.adapters.base import Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.config import settings


async def measure_response_time(adapter, model: str, prompt: str, label: str) -> dict[str, Any]:
    """Measure response time for a single request."""
    start = time.time()
    try:
        result = await adapter.complete(
            messages=[Message(role="user", content=prompt)],
            model=model,
            max_tokens=1000,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "label": label,
            "success": True,
            "elapsed_ms": elapsed_ms,
            "output_tokens": result.output_tokens,
            "chars": len(result.content),
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "label": label,
            "success": False,
            "elapsed_ms": elapsed_ms,
            "error": str(e),
        }


async def profile_adapter(adapter_name: str, adapter, model: str, prompts: dict[str, str]):
    """Profile an adapter with various prompt types."""
    print(f"\n{'='*60}")
    print(f"Profiling {adapter_name} ({model})")
    print(f"{'='*60}")

    results = []
    for label, prompt in prompts.items():
        print(f"\n{label}...")
        result = await measure_response_time(adapter, model, prompt, label)
        results.append(result)

        if result["success"]:
            print(f"  ✓ {result['elapsed_ms']}ms ({result['output_tokens']} tokens, {result['chars']} chars)")
        else:
            print(f"  ✗ {result['elapsed_ms']}ms - Error: {result['error'][:100]}")

        # Avoid rate limits
        await asyncio.sleep(2)

    # Statistics
    successful = [r for r in results if r["success"]]
    if successful:
        times = [r["elapsed_ms"] for r in successful]
        print(f"\n{adapter_name} Statistics:")
        print(f"  Requests: {len(successful)}/{len(results)} successful")
        print(f"  Min: {min(times)}ms")
        print(f"  Max: {max(times)}ms")
        print(f"  Mean: {int(statistics.mean(times))}ms")
        print(f"  Median: {int(statistics.median(times))}ms")
        if len(times) > 1:
            print(f"  Stdev: {int(statistics.stdev(times))}ms")

    return results


async def main():
    """Run profiling for all adapters."""
    print("Adapter Response Time Profiling")
    print("="*60)

    # Test prompts of varying complexity
    prompts = {
        "Tiny (2 words)": "Say hi",
        "Small (simple question)": "What is 2+2?",
        "Medium (explanation)": "Explain how HTTP works in 2-3 sentences.",
        "Large (code generation)": "Write a Python function that calculates the fibonacci sequence using memoization.",
        "Complex (reasoning)": "A farmer has 17 sheep, and all but 9 die. How many are left? Think through this carefully.",
    }

    all_results = {}

    # Profile Claude
    if settings.anthropic_api_key or True:  # OAuth via CLI
        try:
            claude_adapter = ClaudeAdapter()
            claude_results = await profile_adapter(
                "Claude Sonnet 4.5",
                claude_adapter,
                "claude-sonnet-4-5",
                prompts
            )
            all_results["claude"] = claude_results
        except Exception as e:
            print(f"\n⚠ Claude profiling failed: {e}")

    # Profile Gemini
    if settings.gemini_api_key:
        try:
            gemini_adapter = GeminiAdapter()
            gemini_results = await profile_adapter(
                "Gemini 3 Flash",
                gemini_adapter,
                "gemini-3-flash-preview",
                prompts
            )
            all_results["gemini"] = gemini_results
        except Exception as e:
            print(f"\n⚠ Gemini profiling failed: {e}")

    # Overall recommendations
    print(f"\n{'='*60}")
    print("TIMEOUT RECOMMENDATIONS")
    print(f"{'='*60}")

    all_times = []
    for provider_results in all_results.values():
        for r in provider_results:
            if r["success"]:
                all_times.append(r["elapsed_ms"])

    if all_times:
        p95 = sorted(all_times)[int(len(all_times) * 0.95)] if len(all_times) > 1 else max(all_times)
        p99 = sorted(all_times)[int(len(all_times) * 0.99)] if len(all_times) > 1 else max(all_times)

        print(f"\nAll Providers Combined:")
        print(f"  Total requests: {len(all_times)}")
        print(f"  Max response time: {max(all_times)}ms ({max(all_times)/1000:.1f}s)")
        print(f"  P95 response time: {p95}ms ({p95/1000:.1f}s)")
        print(f"  P99 response time: {p99}ms ({p99/1000:.1f}s)")

        # Timeout recommendations
        recommended_timeout = int(max(all_times) * 3)  # 3x max observed
        print(f"\n📊 Recommended Request Timeout: {recommended_timeout}ms ({recommended_timeout/1000:.1f}s)")
        print(f"   (3x max observed: {max(all_times)}ms)")

        # Compare with current plan
        current_plan = 120_000  # 120s in ms
        if recommended_timeout < current_plan:
            ratio = current_plan / recommended_timeout
            print(f"\n✓ Current plan (120s) is {ratio:.1f}x the recommended timeout")
            print(f"  Consider more aggressive timeout: {recommended_timeout/1000:.0f}s")
        else:
            print(f"\n⚠ Current plan (120s) may be too aggressive!")
            print(f"  Observed max: {max(all_times)/1000:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
