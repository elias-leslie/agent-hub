#!/usr/bin/env python3
"""
Test TRUE idle detection vs application-level chunk timeouts.

Key distinction:
- Chunk-level timeout: No SSE events received (application layer)
- Read timeout: No BYTES received on socket (transport layer) = TRUE IDLE

TRUE idle means the TCP connection is stalled - no data flowing at all.
This is different from "model is thinking slowly but connection is healthy."
"""

import asyncio
import time

import httpx


async def test_httpx_read_timeout_semantics():
    """Demonstrate TRUE idle detection at the transport layer."""
    print("="*70)
    print("TRUE IDLE DETECTION: httpx.Timeout semantics")
    print("="*70)

    print("""
httpx.Timeout has four components:
  - connect: Time to establish TCP connection
  - read: Time waiting for ANY bytes to be received
  - write: Time to send request data
  - pool: Time to acquire connection from pool

The 'read' timeout is TRUE IDLE detection:
  - If set to 60s, the connection is considered STALLED if no bytes
    are received for 60 seconds
  - This is at the socket level, not application level
  - Even if model is "thinking", servers typically send:
    * HTTP/2 PING frames (keepalive)
    * SSE comments/heartbeats
    * Partial data fragments
  - If NOTHING comes for read_timeout, connection is truly dead
""")

    # Test 1: Connect timeout (fast failure for unreachable host)
    print("\n" + "-"*70)
    print("Test 1: Connect timeout (unreachable host)")
    print("-"*70)

    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=60.0))
        start = time.time()
        # Use a non-routable IP to test connect timeout
        await client.get("http://10.255.255.1/test")
    except (httpx.ConnectTimeout, httpx.ConnectError) as e:
        elapsed = time.time() - start
        print(f"  ✓ Connect timeout/error after {elapsed:.1f}s: {type(e).__name__}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ✓ Error after {elapsed:.1f}s: {type(e).__name__}: {e}")
    finally:
        await client.aclose()

    # Test 2: Read timeout on slow/stalled server
    print("\n" + "-"*70)
    print("Test 2: Read timeout demonstration")
    print("-"*70)

    print("""
  For a TRUE idle scenario:
  - Server accepts connection (connect succeeds)
  - Server sends HTTP headers (initial response)
  - Server stops sending ANY bytes (read timeout triggers)

  This is different from:
  - Server sends data slowly (read timeout keeps resetting)
  - Server sends SSE heartbeats (read timeout keeps resetting)
""")


async def demonstrate_anthropic_timeout():
    """Show how to configure TRUE idle detection for Anthropic."""
    print("\n" + "="*70)
    print("ANTHROPIC SDK: Configuring TRUE idle detection")
    print("="*70)

    try:
        import anthropic

        print("""
Anthropic SDK accepts httpx.Timeout for precise control:

```python
import anthropic
import httpx

client = anthropic.AsyncAnthropic(
    timeout=httpx.Timeout(
        connect=30.0,   # 30s to establish connection
        read=90.0,      # 90s TRUE IDLE - no bytes = connection dead
        write=30.0,     # 30s to send request
        pool=30.0,      # 30s to get connection from pool
    )
)
```

This is TRUE idle detection because:
- read=90.0 means if NO BYTES flow for 90s, timeout fires
- Extended thinking still sends bytes (thinking events, heartbeats)
- Only truly stalled connections trigger this timeout
""")

        # Show current default
        client = anthropic.AsyncAnthropic()
        print(f"  Current default timeout: {client.timeout}")

    except ImportError:
        print("  (anthropic SDK not available)")


async def demonstrate_google_timeout():
    """Show how to configure TRUE idle detection for Google GenAI."""
    print("\n" + "="*70)
    print("GOOGLE GENAI SDK: Configuring TRUE idle detection")
    print("="*70)

    try:
        from google import genai
        from google.genai import types

        print("""
Google GenAI SDK uses http_options for timeout configuration:

```python
from google import genai
from google.genai import types

client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(
        timeout=90.0,  # Overall request timeout
    )
)
```

Note: Google's SDK may have different timeout semantics.
Check if it supports separate connect/read timeouts.
""")

        # Check available options
        if hasattr(types, 'HttpOptions'):
            import inspect
            sig = inspect.signature(types.HttpOptions)
            print(f"  HttpOptions parameters: {list(sig.parameters.keys())}")

    except ImportError as e:
        print(f"  (google-genai SDK not available: {e})")


async def main():
    """Run all TRUE idle detection tests."""
    print("\n" + "="*70)
    print("TRUE IDLE DETECTION ANALYSIS")
    print("="*70)

    print("""
CRITICAL INSIGHT:
================

My previous approach was WRONG. I was measuring:
  ❌ Time between SSE events (application layer)

Correct approach measures:
  ✅ Time between ANY bytes on socket (transport layer)

Why this matters:
-----------------
1. Extended thinking: Model may emit no visible chunks while thinking,
   but the connection is ALIVE (HTTP keepalives, SSE comments flow)

2. Slow generation: Model may generate tokens slowly, but bytes
   still flow - connection is NOT idle

3. TRUE idle: TCP socket has no activity at all - connection is STALLED
   This is what read timeout detects

Implementation:
---------------
Don't use asyncio.wait_for on chunk iteration!
Instead, configure SDK-level timeouts:

```python
# Anthropic
client = anthropic.AsyncAnthropic(
    timeout=httpx.Timeout(connect=30.0, read=90.0, write=30.0, pool=30.0)
)

# Google (check SDK docs for exact syntax)
client = genai.Client(http_options=...)
```
""")

    await test_httpx_read_timeout_semantics()
    await demonstrate_anthropic_timeout()
    await demonstrate_google_timeout()

    print("\n" + "="*70)
    print("CORRECTED IMPLEMENTATION APPROACH")
    print("="*70)

    print("""
1. CONNECTION TIMEOUT (30s):
   - httpx connect timeout
   - Detects: DNS failure, network unreachable, firewall blocking

2. TRUE IDLE / READ TIMEOUT (90s):
   - httpx read timeout
   - Detects: Server hung, connection stalled, no bytes flowing
   - Does NOT falsely trigger on: slow thinking, slow generation

3. OVERALL REQUEST TIMEOUT (120s):
   - Total time for entire request
   - Catches edge cases where bytes trickle but response never completes

4. RETRY LOGIC:
   - 503/429 errors: Retry with exponential backoff
   - Timeout errors: May retry if retriable

NO chunk-level asyncio.wait_for needed for idle detection!
The SDK's HTTP timeout handles TRUE idle at the transport layer.
""")


if __name__ == "__main__":
    asyncio.run(main())
