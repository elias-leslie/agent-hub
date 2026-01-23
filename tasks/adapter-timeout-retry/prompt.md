# Adapter Timeout, Retry & Consolidation

## Problem Statement

The Gemini and Claude adapters have no timeout or retry logic. When Gemini returns 503 (overloaded) or hangs, requests wait indefinitely. This caused the consult skill timeout issues identified in the access control audit.

## Current State

### Adapters (backend/app/adapters/)
- `base.py` - Abstract `ProviderAdapter` class, shared types
- `claude.py` - Claude adapter (OAuth via CLI + API key fallback)
- `gemini.py` - Gemini adapter (API key)
- `openai.py` - OpenAI-compatible adapter

### What's Missing
1. **No connection timeout** - Can't reach API? Wait forever.
2. **No request timeout** - Non-streaming requests wait indefinitely.
3. **No idle timeout on streams** - Stalled stream? Wait forever.
4. **No retry logic** - 503/429 errors fail immediately instead of retrying.

### What Exists (but unused for timeout)
- Both adapters support streaming (`adapter.stream()`)
- Stream chunks act as implicit keepalive (if chunks flow, it's alive)
- But no tracking of `last_chunk_time` or idle detection

## Proposed Solution

| Scenario | Timeout | Action |
|----------|---------|--------|
| Connection (can't reach API) | 30s | Fail immediately |
| Non-streaming response | 120s | Fail, trigger retry |
| Streaming idle (no chunks) | 60s | Fail, trigger retry |
| 503/429 errors | - | Retry 3x with exponential backoff |

### Implementation Approach
1. Add `asyncio.wait_for()` wrapper for non-streaming calls
2. Track `last_chunk_time` in streaming, fail if idle > 60s
3. Add retry decorator with exponential backoff for transient errors
4. Emit synthetic "heartbeat" events during long operations (optional)

## Consolidation Questions

Before implementing, evaluate:

1. **Why 3 separate adapters?**
   - Claude, Gemini, OpenAI all do similar things
   - Could there be a single adapter with provider-specific config?
   - Or is the separation justified by different auth/API patterns?

2. **Shared retry/timeout logic**
   - Should this live in `base.py` as a mixin/decorator?
   - Or in each adapter separately?

3. **Streaming architecture**
   - All three support streaming
   - Could idle timeout be implemented once in base class?

4. **Error handling patterns**
   - Each adapter has similar try/except blocks for 429/503/401
   - Could this be unified?

## Files to Examine

```
backend/app/adapters/base.py      # Abstract base, shared types
backend/app/adapters/claude.py    # ~500 lines, OAuth + API key
backend/app/adapters/gemini.py    # ~400 lines, API key
backend/app/adapters/openai.py    # OpenAI-compatible
backend/app/api/complete.py       # Uses adapters, has _get_adapter()
```

## Acceptance Criteria

1. Non-streaming requests timeout after 120s
2. Streaming requests fail if no chunks for 60s
3. Transient errors (503, 429) retry with exponential backoff
4. Existing functionality unchanged (tests pass)
5. Clear decision on consolidation (document rationale if keeping separate)

## Run With

```bash
/plan_it "Implement timeout and retry logic for LLM adapters with consolidation review"
```

Or reference this file:
```bash
/plan_it  # Then paste: "See tasks/adapter-timeout-retry/prompt.md for full context"
```
