#!/usr/bin/env python3
"""
Load test for Agent Hub /api/v1/chat/completions endpoint.

Tests concurrent request handling and measures latency percentiles.

Usage:
    python scripts/load_test.py --concurrent 100 --requests 200
    python scripts/load_test.py --concurrent 10 --requests 50  # Quick test
    python scripts/load_test.py --mock  # Test API overhead only (no model call)
"""

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

import httpx

BASE_URL = "http://localhost:8003"
ENDPOINT = "/api/v1/chat/completions"
HEALTH_ENDPOINT = "/health"

# Minimal request payload for testing
# Use Gemini - Claude OAuth spawns CLI subprocesses (heavy, not suitable for load test)
TEST_PAYLOAD = {
    "model": "gemini-3-flash-preview",  # Fast, uses direct SDK (no subprocess)
    "messages": [{"role": "user", "content": "Say 'OK' in one word."}],
    "max_tokens": 10,
    "temperature": 0,
    "persist_session": False,  # Don't persist for load tests
}


@dataclass
class RequestResult:
    """Result of a single request."""

    success: bool
    latency_ms: float
    status_code: int | None = None
    error: str | None = None


async def make_request(
    client: httpx.AsyncClient,
    request_id: int,
    mock: bool = False,  # noqa: ARG001
) -> RequestResult:
    """Make a single request and measure latency."""
    start = time.perf_counter()
    endpoint = HEALTH_ENDPOINT if mock else ENDPOINT
    try:
        if mock:
            response = await client.get(endpoint, timeout=30.0)
        else:
            response = await client.post(endpoint, json=TEST_PAYLOAD, timeout=30.0)
        latency_ms = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            return RequestResult(success=True, latency_ms=latency_ms, status_code=200)
        else:
            return RequestResult(
                success=False,
                latency_ms=latency_ms,
                status_code=response.status_code,
                error=response.text[:200],
            )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(success=False, latency_ms=latency_ms, error=str(e)[:200])


async def run_batch(
    client: httpx.AsyncClient, batch_size: int, start_id: int, mock: bool = False
) -> list[RequestResult]:
    """Run a batch of concurrent requests."""
    tasks = [make_request(client, start_id + i, mock=mock) for i in range(batch_size)]
    return await asyncio.gather(*tasks)


async def run_load_test(
    concurrent: int, total_requests: int, mock: bool = False
) -> dict:
    """Run the load test with specified concurrency."""
    mode = "MOCK (health check)" if mock else "REAL (model calls)"
    print(f"Load Test: {total_requests} requests, {concurrent} concurrent [{mode}]")
    print(f"Target: {BASE_URL}{ENDPOINT}")
    print("-" * 50)

    results: list[RequestResult] = []

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Warm up with a single request
        print("Warming up...")
        warmup = await make_request(client, 0, mock=mock)
        if not warmup.success:
            print(f"Warmup failed: {warmup.error}")
            print("Is the backend running? Try: bash ~/agent-hub/scripts/restart.sh")
            return {"error": "warmup_failed"}

        print(f"Warmup: {warmup.latency_ms:.0f}ms")

        # Run batches
        completed = 0
        start_time = time.perf_counter()

        while completed < total_requests:
            batch_size = min(concurrent, total_requests - completed)
            batch_results = await run_batch(client, batch_size, completed, mock=mock)
            results.extend(batch_results)
            completed += batch_size

            # Progress update
            success_count = sum(1 for r in results if r.success)
            print(f"Progress: {completed}/{total_requests} ({success_count} success)")

        total_time = time.perf_counter() - start_time

    # Calculate statistics
    success_results = [r for r in results if r.success]
    failed_results = [r for r in results if not r.success]

    if not success_results:
        print("All requests failed!")
        for r in failed_results[:5]:
            print(f"  Error: {r.error}")
        return {"error": "all_failed"}

    latencies = [r.latency_ms for r in success_results]
    latencies.sort()

    def percentile(data: list[float], p: float) -> float:
        """Calculate percentile."""
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f])

    stats = {
        "total_requests": total_requests,
        "concurrent": concurrent,
        "success_count": len(success_results),
        "failure_count": len(failed_results),
        "success_rate": len(success_results) / total_requests * 100,
        "total_time_sec": total_time,
        "requests_per_sec": total_requests / total_time,
        "latency_ms": {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
        },
    }

    # Print results
    print()
    print("=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"Total requests: {stats['total_requests']}")
    print(f"Concurrent: {stats['concurrent']}")
    print(f"Success: {stats['success_count']} ({stats['success_rate']:.1f}%)")
    print(f"Failed: {stats['failure_count']}")
    print(f"Total time: {stats['total_time_sec']:.2f}s")
    print(f"Throughput: {stats['requests_per_sec']:.1f} req/s")
    print()
    print("Latency (ms):")
    print(f"  Min: {stats['latency_ms']['min']:.0f}")
    print(f"  Mean: {stats['latency_ms']['mean']:.0f}")
    print(f"  Median: {stats['latency_ms']['median']:.0f}")
    print(f"  p95: {stats['latency_ms']['p95']:.0f}")
    print(f"  p99: {stats['latency_ms']['p99']:.0f}")
    print(f"  Max: {stats['latency_ms']['max']:.0f}")
    print()

    # Check p99 requirement
    p99_limit = 2000  # 2 seconds
    if stats["latency_ms"]["p99"] < p99_limit:
        print(f"PASS: p99 ({stats['latency_ms']['p99']:.0f}ms) < {p99_limit}ms")
    else:
        print(f"FAIL: p99 ({stats['latency_ms']['p99']:.0f}ms) >= {p99_limit}ms")

    # Print errors if any
    if failed_results:
        print()
        print("Sample errors:")
        for r in failed_results[:3]:
            print(f"  [{r.status_code}] {r.error}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Load test Agent Hub API")
    parser.add_argument(
        "--concurrent",
        "-c",
        type=int,
        default=100,
        help="Number of concurrent requests",
    )
    parser.add_argument(
        "--requests", "-n", type=int, default=200, help="Total number of requests"
    )
    parser.add_argument(
        "--mock",
        "-m",
        action="store_true",
        help="Mock mode - test API overhead only (health endpoint)",
    )
    args = parser.parse_args()

    asyncio.run(run_load_test(args.concurrent, args.requests, mock=args.mock))


if __name__ == "__main__":
    main()
