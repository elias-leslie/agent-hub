# Adapter Registry Rewrite — Summary

**Date**: February 2026
**Commits**: `3c786fd` → `f567a75` (8 phases, 16 commits including auto-format)

## Problem

The adapter layer had grown organically and suffered from:

1. **4 duplicate factory dictionaries** — `helpers_adapters.py`, `provider_chain.py`, `agent_routing_utils.py`, and `provider_utils.py` each maintained their own provider→adapter mapping, often with different sets of providers.
2. **2 near-identical tool event processors** — `tool_claude_processor.py` (152 LOC) and `tool_gemini_processor.py` (169 LOC) did the same thing with minor differences.
3. **Hard-coded provider gates** — `_core_helpers.py:98` had `if provider in ("claude", "gemini")`, blocking tool execution for 7 other providers.
4. **Bare mutable globals** — Gemini adapter used module-level `_auth_preference` and `_vertex_project` variables.
5. **Duplicated CloudCode HTTP client** — `gemini_cloudcode.py` and `cloudcode_claude.py` each implemented their own HTTP client logic.
6. **Unwired agent config** — Johnny's `thinking_level`, `fallback_models`, and `escalation_model_id` fields existed in the DB but were never passed to the completion pipeline.
7. **Dead parameters** — `cache_retention` was accepted by `ClaudeAdapter.complete()` but never forwarded to the Anthropic SDK.
8. **No cost tracking** — `log_token_usage()` always received `cost_usd=0.0` despite a full model cost catalog existing.

## What Changed

### Phase 0: Unified Adapter Registry (`3c786fd`)

Created `backend/app/adapters/registry.py` — a single registry for all 9 providers:

```
claude, gemini, cloudcode, codex, openai, openrouter, xai, zhipu, minimax
```

**Key design decisions:**
- Lazy factories (closures with inline imports) to avoid circular dependencies
- Instance cache with per-provider invalidation
- Model→provider resolution using existing `catalog.py` with prefix/name fallback

All 4 factory sites now delegate to `registry.get_adapter()`.

### Phase 1: Unified Tool Execution (`d87b01a`)

Merged two separate tool processing paths into one:

| Before | After |
|--------|-------|
| `tool_claude_processor.py` (152 LOC) | `tool_event_processor.py` (171 LOC) — handles all providers |
| `tool_gemini_processor.py` (169 LOC) | *(deleted)* |
| `_complete_with_claude_tools()` | `_complete_with_tools()` — one function |
| `_complete_with_gemini_tools()` | *(merged)* |
| `_run_claude_tool_loop()` | `_run_tool_loop()` — one loop |
| `_run_gemini_tool_loop()` | *(merged)* |
| `finalize_claude_response()` | `finalize_response()` — one finalizer |
| `finalize_gemini_response()` | *(merged)* |

**Event adaptation layer** — three adapters normalize provider-specific events to `ToolEvent`:
- `claude_event_adapter.py` — Claude Agent SDK messages → ToolEvent
- `openai_event_adapter.py` — OpenAI-compat CompletionResult → ToolEvent
- Native: Gemini/CloudCode already emit ToolEvent

**Result**: Tool execution works for all registered tool-capable providers. No `if provider == "claude"` branching anywhere in the pipeline.

### Phase 2: Shared CloudCode Client (`c87d216`)

Extracted `CloudCodeClient` into `backend/app/adapters/cloudcode_client.py`, shared by:
- `gemini_cloudcode.py` (Gemini via CloudCode PA)
- `cloudcode_claude.py` (Claude via CloudCode PA/Antigravity)

Also replaced Gemini's bare mutable module globals with a `GeminiSettings` dataclass.

### Phase 3: Capability-Aware Routing (`abf7726`)

Added `ProviderCapabilities` to the registry:

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_streaming: bool = True
    supports_tool_execution: bool = False
    supports_thinking: bool = False
    supports_images: bool = False
    supports_cache_retention: bool = False
```

Each provider declares capabilities at registration time. Routing code queries:

```python
from app.adapters.registry import supports_tools

if supports_tools(provider):
    # route to tool execution
```

No more hard-coded provider name lists.

### Phase 4: Cost Wiring + StreamEvent Expansion (`767fa5c`)

- Wired existing `estimate_cost()` from `token_counter.py` into the SSE `done` event
- Added `cost_usd`, `thinking_tokens`, `cache_read_tokens`, `cache_write_tokens` to `StreamingChunk`
- Added `turn_start`/`turn_end` event types and `turn` field to `StreamEvent`
- Added `provider`/`model` provenance fields to `Message`

Frontend receives real cost data now (fields are optional — existing frontend ignores them via switch/case).

### Phase 5: Cache Retention + Abort + Johnny Wiring (`7d7881d`)

**Cache retention**: `ClaudeAdapter._apply_cache_control()` converts system text to a cache-controlled content block with TTL:

```python
[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
```

**Abort signal**: Claude and Gemini `stream()` methods check `kwargs.get("abort_event")` — an `asyncio.Event` that callers set to request graceful cancellation.

**Johnny wiring**: `_resolve_johnny()` now returns `thinking_level` from the agent's DB config. Passed through `WakeInput` → `dispatch_wake()` → `complete_internal()`.

### Phase 6: EventStream Dual Interface (`24af051`)

Created `backend/app/adapters/event_stream.py`:

```python
class EventStream[T, R]:
    async def push(self, event: T) -> None: ...
    async def end(self, result: R | None = None) -> None: ...
    def result(self) -> asyncio.Future[R]: ...  # resolves on completion
    def __aiter__(self) -> AsyncIterator[T]: ...

    @classmethod
    def from_async_iterator(cls, iterator, result_extractor=None) -> EventStream: ...
```

Supports both async iteration (streaming events) and `.result()` awaiting (get final result). Johnny can stream progress to Hatchet while awaiting the final result.

### Phase 7: Cleanup (`f567a75`)

- Deleted `tool_claude_processor.py` and `tool_gemini_processor.py`
- Removed backward-compat aliases (`MockEvent`→`ToolEvent`, `MockMessage`→`ToolMessage`, `MockContentBlock`→`ToolContentBlock`)
- Removed legacy function aliases from handler/finalizer modules
- Removed `USE_UNIFIED_TOOL_PROCESSOR` feature flag (unified path is now the only path)

## Architecture Overview

```
                    ┌─────────────────────┐
                    │   registry.py       │
                    │   (9 providers)     │
                    │   get_adapter()     │
                    │   supports_tools()  │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌─────────────┐ ┌──────────────┐ ┌───────────────┐
    │ Claude      │ │ Gemini       │ │ OpenAI-compat │
    │ Agent SDK   │ │ google-genai │ │ httpx/openai  │
    └──────┬──────┘ └──────┬───────┘ └──────┬────────┘
           │               │                │
           ▼               ▼                ▼
    ┌──────────────────────────────────────────────┐
    │          Event Adaptation Layer               │
    │  claude_event_adapter  │  (native ToolEvent) │
    │  openai_event_adapter  │                     │
    └──────────────────┬───────────────────────────┘
                       ▼
    ┌──────────────────────────────────────────────┐
    │       tool_event_processor.py                │
    │       (unified — all providers)              │
    └──────────────────┬───────────────────────────┘
                       ▼
    ┌──────────────────────────────────────────────┐
    │       tool_handler_utils.py                  │
    │       _run_tool_loop() → SSE events          │
    └──────────────────────────────────────────────┘
```

## Key Files

| File | Purpose | LOC |
|------|---------|-----|
| `adapters/registry.py` | Unified adapter registry with capabilities | 315 |
| `adapters/event_stream.py` | Dual-interface EventStream | 151 |
| `adapters/cloudcode_client.py` | Shared CloudCode PA HTTP client | 28 (re-export) |
| `adapters/gemini_events.py` | ToolEvent/ToolMessage/ToolContentBlock definitions | 50 |
| `api/complete/tool_event_processor.py` | Unified event processor (all providers) | 171 |
| `api/complete/tool_handler_utils.py` | Unified tool loop orchestration | 120 |
| `api/complete/tool_router.py` | Tool execution routing | 97 |
| `api/complete/claude_event_adapter.py` | Claude SDK → ToolEvent adapter | ~40 |
| `api/complete/openai_event_adapter.py` | OpenAI-compat → ToolEvent adapter | ~30 |

## What Johnny Gained

| Capability | Before | After |
|-----------|--------|-------|
| Thinking | Not passed to adapter | `thinking_level` from agent DB config |
| Cost tracking | `cost_usd=0.0` always | Real USD from model catalog |
| Cache retention | Parameter ignored | Active — 1h TTL on system prompts |
| Abort signal | 300s Hatchet kill | Graceful `asyncio.Event` cancellation |
| Streaming progress | Wait for full response | EventStream: iterate + await result |
| Tool providers | 2 (Claude, Gemini) | 10 (all except Minimax) |

## How to Add a New Provider

1. Create `backend/app/adapters/new_provider.py` implementing `ProviderAdapter`
2. Add a factory closure and `register()` call in `registry.py:_ensure_registered()`:

```python
def _new_provider() -> ProviderAdapter:
    from app.adapters.new_provider import NewProviderAdapter
    return NewProviderAdapter()

register("new_provider", _new_provider, ProviderCapabilities(
    supports_tool_execution=True,
    supports_thinking=False,
    supports_images=True,
))
```

3. Add model entries to `constants/catalog.py`
4. If tool execution uses a non-standard event format, create an event adapter in `api/complete/`

That's it. No other files need modification — the registry handles routing, capability queries, and caching automatically.

## SSE Contract (unchanged)

The frontend SSE contract is preserved. All new fields are additive:

```
done event gains: cost_usd, thinking_tokens, cache_read_tokens, cache_write_tokens
New event types: turn_start, turn_end (ignored by current frontend)
```

Existing frontend code continues to work without modification.

## Test Coverage

- `tests/adapters/test_registry.py` — 27 tests (registry, capabilities, model resolution)
- `tests/api/complete/test_streaming_cost.py` — 8 tests (cost wiring)
- `tests/adapters/test_event_stream.py` — 9 tests (dual interface)
- All pre-existing tests pass (1476 passed, 28 skipped)
