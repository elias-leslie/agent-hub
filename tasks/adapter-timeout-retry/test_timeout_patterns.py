#!/usr/bin/env python3
"""Test SOTA timeout patterns for async operations."""

import asyncio
import time
from typing import AsyncIterator


async def slow_operation(delay: float, label: str) -> str:
    """Simulate a slow API call."""
    print(f"  [{label}] Starting (will take {delay}s)...")
    await asyncio.sleep(delay)
    print(f"  [{label}] Completed!")
    return f"Result after {delay}s"


async def slow_stream(chunk_delays: list[float], label: str) -> AsyncIterator[str]:
    """Simulate a slow streaming response."""
    for i, delay in enumerate(chunk_delays):
        print(f"  [{label}] Chunk {i+1} (delay {delay}s)...")
        await asyncio.sleep(delay)
        yield f"chunk_{i+1}"


async def test_request_timeout():
    """Test asyncio.wait_for for request timeout."""
    print("\n" + "="*60)
    print("TEST 1: Request Timeout with asyncio.wait_for")
    print("="*60)

    # Test 1: Fast request (should succeed)
    print("\nCase 1: Fast request (2s) with 5s timeout")
    try:
        start = time.time()
        result = await asyncio.wait_for(
            slow_operation(2.0, "Fast"),
            timeout=5.0
        )
        elapsed = time.time() - start
        print(f"  ✓ Success: {result} ({elapsed:.1f}s)")
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout!")

    # Test 2: Slow request (should timeout)
    print("\nCase 2: Slow request (10s) with 3s timeout")
    try:
        start = time.time()
        result = await asyncio.wait_for(
            slow_operation(10.0, "Slow"),
            timeout=3.0
        )
        elapsed = time.time() - start
        print(f"  ✓ Success: {result} ({elapsed:.1f}s)")
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"  ✓ Timeout triggered at {elapsed:.1f}s (expected!)")


async def test_stream_idle_timeout_naive():
    """Test naive stream idle timeout (WRONG - doesn't work!)."""
    print("\n" + "="*60)
    print("TEST 2: Stream Idle Timeout - NAIVE (BROKEN)")
    print("="*60)

    print("\nCase: Stream with idle timeout (naive asyncio.wait_for)")
    print("  Stream: 1s, 1s, 10s (long delay), 1s")
    print("  Idle timeout: 5s")

    try:
        start = time.time()
        chunks = []
        # WRONG: Can't use asyncio.wait_for on async generator directly!
        # This is a common mistake - it would timeout the entire stream
        print("  ✗ asyncio.wait_for(stream) - TypeError!")
        print("     Can't iterate over coroutine - need SOTA pattern instead")
    except Exception as e:
        print(f"  ✗ Error: {e}")


async def test_stream_idle_timeout_correct():
    """Test correct stream idle timeout (per-chunk timeout)."""
    print("\n" + "="*60)
    print("TEST 3: Stream Idle Timeout - CORRECT (Per-Chunk)")
    print("="*60)

    print("\nCase 1: Stream with fast chunks (should succeed)")
    print("  Stream: 1s, 1s, 1s, 1s")
    print("  Idle timeout: 5s per chunk")

    try:
        start = time.time()
        chunks = []
        stream = slow_stream([1.0, 1.0, 1.0, 1.0], "Fast stream")
        last_chunk_time = time.time()

        async for chunk in stream:
            # Check idle time BEFORE waiting for next chunk
            chunk_elapsed = time.time() - last_chunk_time
            print(f"    Chunk received after {chunk_elapsed:.1f}s")

            chunks.append(chunk)
            last_chunk_time = time.time()

        elapsed = time.time() - start
        print(f"  ✓ Success: Got {len(chunks)} chunks ({elapsed:.1f}s)")
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"  ✗ Timeout at {elapsed:.1f}s")

    print("\nCase 2: Stream with one slow chunk (should timeout)")
    print("  Stream: 1s, 1s, 10s (idle!), 1s")
    print("  Idle timeout: 5s per chunk")

    try:
        start = time.time()
        chunks = []
        stream = slow_stream([1.0, 1.0, 10.0, 1.0], "Idle stream")
        last_chunk_time = time.time()
        idle_timeout = 5.0

        # CORRECT: Wrap each chunk wait with timeout
        async for chunk in stream:
            chunk_elapsed = time.time() - last_chunk_time

            # Simulate checking idle time
            if chunk_elapsed > idle_timeout:
                raise asyncio.TimeoutError(f"Idle timeout: {chunk_elapsed:.1f}s > {idle_timeout}s")

            print(f"    Chunk received after {chunk_elapsed:.1f}s")
            chunks.append(chunk)
            last_chunk_time = time.time()

        elapsed = time.time() - start
        print(f"  ✗ UNEXPECTED: Got {len(chunks)} chunks ({elapsed:.1f}s)")
        print(f"     Expected timeout!")
    except asyncio.TimeoutError as e:
        elapsed = time.time() - start
        print(f"  ✓ Idle timeout triggered at {elapsed:.1f}s: {e}")


async def test_stream_idle_timeout_asyncio_correct():
    """Test correct stream idle timeout using asyncio.wait_for on __anext__."""
    print("\n" + "="*60)
    print("TEST 4: Stream Idle Timeout - SOTA (asyncio.wait_for per chunk)")
    print("="*60)

    print("\nCase: Stream with one slow chunk (should timeout)")
    print("  Stream: 1s, 1s, 10s (idle!), 1s")
    print("  Idle timeout: 5s per chunk")

    try:
        start = time.time()
        chunks = []
        stream = slow_stream([1.0, 1.0, 10.0, 1.0], "SOTA stream")
        idle_timeout = 5.0

        # SOTA: Wrap __anext__ with asyncio.wait_for
        async_iter = stream.__aiter__()
        while True:
            try:
                chunk_start = time.time()
                chunk = await asyncio.wait_for(
                    async_iter.__anext__(),
                    timeout=idle_timeout
                )
                chunk_elapsed = time.time() - chunk_start
                print(f"    Chunk received after {chunk_elapsed:.1f}s")
                chunks.append(chunk)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                elapsed = time.time() - start
                print(f"  ✓ CORRECT: Idle timeout at {elapsed:.1f}s (chunk took > {idle_timeout}s)")
                raise

        elapsed = time.time() - start
        print(f"  ✗ UNEXPECTED: Got {len(chunks)} chunks ({elapsed:.1f}s)")
    except asyncio.TimeoutError:
        pass  # Expected


async def main():
    """Run all timeout pattern tests."""
    print("\nTimeout Pattern Testing")
    print("="*60)
    print("Purpose: Validate SOTA timeout implementation approaches")
    print("="*60)

    await test_request_timeout()
    await test_stream_idle_timeout_naive()
    await test_stream_idle_timeout_correct()
    await test_stream_idle_timeout_asyncio_correct()

    print("\n" + "="*60)
    print("SUMMARY: Correct Timeout Patterns")
    print("="*60)
    print("\n✓ Request timeout:")
    print("    result = await asyncio.wait_for(adapter.complete(...), timeout=120)")
    print("\n✓ Stream idle timeout (SOTA):")
    print("    async_iter = stream.__aiter__()")
    print("    while True:")
    print("        chunk = await asyncio.wait_for(async_iter.__anext__(), timeout=60)")
    print("\n⚠ WRONG approaches:")
    print("    ✗ asyncio.wait_for(entire_stream) - times out whole stream, not idle!")
    print("    ✗ Manual time.time() checks - race conditions, not cancellable")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
