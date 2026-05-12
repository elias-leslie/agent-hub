# Agent-Hub Current Adapter + Harness Surface — Audit Catalog

**Current-state baseline for the convergence refactor.** Generated as Phase 0.3 of task `task-e65e9ee0`.

- **Scope:** `backend/app/adapters/` (67 files) + `backend/app/api/complete/` (66 files) + every other location where the relevant types are re-defined
- **Branch:** `task-e65e9ee0/main` (checkpointed)
- **Comparison target:** pi-mono's `packages/ai/src/` (see `pi-mono-catalog.md`)

> This document is the immutable current-state baseline. Diff against `pi-mono-catalog.md` to drive `convergence-map.md`.

---

## 1. Top-level layout

### `backend/app/adapters/` — 67 .py files, 10,412 LOC

```
adapters/
├── __init__.py                          31L   — public exports
│
├── base.py                             169L   — ProviderAdapter ABC (5 methods)
├── types.py                            132L   — StreamEvent, Message, CompletionResult, ToolCallResult, ContainerState, CacheMetrics
├── runtime_session.py                   81L   — ProviderRuntimeSession ABC + StreamBackedRuntimeSession
├── registry.py                         401L   — Adapter factory registry with lazy imports & caching
├── errors.py                           126L   — ProviderError, AuthenticationError, RateLimitError, CircuitBreakerError
├── _errors_types.py                     69L
├── _errors_retry_delay.py               78L
├── event_stream.py                     158L   — Legacy complete()→stream() bridge adapters
├── tool_result_payload.py               24L   — ToolResultPayload (frozen dataclass)
├── thinking.py                          77L   — Extended-thinking config
├── utils.py                             87L   — ToolCallIdNormalizer + shared utilities
│
├── claude.py                           210L   — ClaudeAdapter (hybrid CLI + direct API)
├── claude_direct.py                    481L   — Anthropic SDK direct calls (NON-STREAMING messages.create paths)
├── claude_oauth.py                     171L   — OAuth token + direct-API wrapper
├── claude_streaming.py                 252L   — Streaming via direct API
├── claude_auth.py                      196L   — CLI OAuth flows
├── claude_tools_helpers.py             275L   — Tool calling via Claude SDK
├── claude_tool_events.py               178L   — Claude SDK → canonical ToolEvent translation
├── claude_tools_stream.py              217L   — Streaming tool loops for CLI
├── claude_tools_mcp.py                  92L   — MCP tool integration
├── claude_tools_permissions.py          90L   — Tool permission enforcement
├── claude_tools_query_session.py       309L   — Session state queries via SDK
├── _claude_tool_session.py             133L   — ClaudeToolSessionMixin (tool-session methods)
├── _claude_sdk_builder.py              164L   — SDK client construction
├── _claude_settings.py                 184L   — Config defaults
├── _claude_constants.py                 73L   — Model names, thinking budgets
├── _claude_json_utils.py                78L   — JSON helpers
├── _claude_result_metadata.py           59L   — Cache metrics extraction
├── claude_utils.py                     164L   — Shared utilities
│
├── codex_oauth.py                      635L   — CodexOAuthAdapter (Claude SDK OAuth — separate from claude_*)
├── codex_auth.py                       289L   — OAuth token management
├── codex_sse.py                        343L   — SSE streaming
├── codex_token_cache.py                 72L   — Token caching
│
├── gemini.py                           183L   — GeminiAdapter (API-key failover)
├── gemini_adapter_ops.py               126L   — SDK completion + health (HAS NON-STREAMING)
├── gemini_adapter_stream.py            214L   — Streaming completions
├── gemini_tools.py                     249L   — Tool calling + tool-loop
├── gemini_messages.py                  112L   — Message conversion
├── gemini_response.py                  173L   — Response parsing
├── gemini_events.py                     50L   — ToolEvent, ToolContentBlock, ToolMessage (canonical types live here!)
├── gemini_errors.py                    205L   — Error classification + retry
├── gemini_thinking.py                   56L   — Extended-thinking mapping
├── gemini_image.py                     175L   — Image handling
├── gemini_config.py                     96L   — SDK setup
├── gemini_utils.py                     166L   — Utilities
├── gemini_adapter_settings.py           13L   — Settings stub
│
├── openai_compat.py                    191L   — OpenAICompatibleAdapter base class
├── _openai_compat_helpers.py           406L   — Response normalization + error handling
├── openai.py                            24L   — OpenAIAdapter stub
├── openai_tool_events.py               147L   — Tool event adaptation
├── _openai_tool_loop.py                 88L   — Tool loop
├── xai.py                              293L   — XAIAdapter (subclass)
├── openrouter.py                        63L   — OpenRouterAdapter (subclass)
│
├── kimi_code.py                        351L   — KimiCodeAdapter (HAS NON-STREAMING in complete_with_tools)
├── moonshot.py                          24L   — stub
├── deepseek.py                          24L   — stub
├── zhipu.py                             24L   — stub
├── nvidia.py                            41L   — stub
├── minimax.py                           39L   — stub
├── local.py                             22L   — stub
├── cloudflare.py                        92L   — Cloudflare text adapter
│
├── image_base.py                        58L   — Image adapter base (OUT OF SCOPE)
├── cloudflare_image.py                 193L   — OUT OF SCOPE
├── nvidia_image.py                     218L   — OUT OF SCOPE
└── minimax_image.py                    178L   — OUT OF SCOPE
```

### `backend/app/api/complete/` — 66 .py files, 11,423 LOC

```
api/complete/
├── __init__.py                          81L   — public exports
├── endpoints.py                         69L   — FastAPI router: /complete, /complete/cancel, /estimate
├── async_endpoints.py                  133L   — GET /complete/tasks/{task_id}, DELETE /complete/tasks/{task_id}/cancel
├── schemas.py                           60L   — Response schemas
├── request_schemas.py                  349L   — CompletionRequest, ToolDefinition, ResponseFormat, WorkContext
├── response_schemas.py                 166L   — CompletionResponse, streaming schemas
├── types.py                             43L   — CompletionInternalResult (one of multiple)
├── usage_schemas.py                     76L   — Token usage models
├── validation.py                        80L   — Request validation
│
├── complete_orchestrator.py            188L   — orchestrate_completion() top-level dispatch
├── complete_execution.py               221L   — Non-streaming completion path
│
├── tool_handlers.py                    205L   — _complete_with_tools() — sync tool handler
├── tool_handler_utils.py               301L   — _ExecutionState + _run_tool_loop() (sync)
├── multi_turn_loop.py                  172L   — execute_single_turn()
├── multi_turn_executor.py              139L   — run_multi_turn_completion()
├── multi_turn_helpers.py               238L   — TurnLoopConfig + process_turn_result()
│
├── streaming.py                        205L   — orchestrate_streaming() entry
├── streaming_handlers.py               313L   — Tool-loop streaming handlers
├── streaming_context.py                135L   — StreamContext (async-context-var session)
├── streaming_persistence.py            411L   — SSE building + stream progress publishing
├── streaming_tool_loop.py              156L   — iter_stream_sse_with_tools() — public entry
├── streaming_tool_executor.py          171L   — append_turn_messages, collect_turn_events, iter_unresolved_tools
├── streaming_tool_messages.py          102L   — sse_for_simple_event()
├── streaming_runtime_session.py        415L   — iter_runtime_session_sse_with_tools() — alt path via ProviderRuntimeSession
│
├── agent_loop.py                       243L   — Agent-driven multi-turn loops
│
├── session_manager.py                  198L   — get_or_create_session()
├── session_setup.py                    110L   — Session initialization
├── _session_helpers.py                 162L   — load_session, maybe_reset_persona_session
├── runtime_session_registry.py          43L   — RuntimeSessionRegistry
│
├── request_setup.py                    350L   — Request preprocessing
├── result_builder.py                   104L   — Result construction
├── result_finalizer.py                 135L   — Final result assembly
│
├── tool_event_processor.py             297L   — process_tool_event()
├── tool_event_storage.py               152L   — Tool result persistence
├── tool_models.py                       53L   — AgentProgress, ToolExecutionResult
├── tool_progress.py                    115L   — ProgressTracker
├── tool_provisioner.py                 187L   — Tool setup + provisioning
├── tool_response_finalizer.py          221L   — Response finalization after tool execution
├── tool_result_builder.py              146L   — Result construction from tool outputs
├── tool_router.py                       93L   — Tool routing
│
├── context_compaction.py               184L   — Context window management
├── cache_handler.py                    110L   — Prompt cache handling
├── citation_tracker.py                 199L   — Citation tracking from memory
├── _citation_helpers.py                222L
├── memory_handler.py                   102L   — Semantic memory injection
├── finish_reason_handler.py            157L   — Finish reason processing
├── precision_search_guidance.py        256L   — Search guidance injection
├── closeout_policy.py                  259L   — Tool-loop closeout + recovery strategies
├── turn_processor.py                   157L
├── turn_processor_helpers.py            69L
├── turn_budget.py                       41L   — resolve_tool_max_turns()
├── error_summary.py                     71L   — Error aggregation
│
├── execution_observability.py          138L   — Execution telemetry + tracing
├── handlers.py                         118L   — Generic handler dispatch
├── handler_helpers.py                  292L   — Handler utility functions
├── error_handlers.py                   211L   — Error handling + recovery
├── event_helpers.py                    105L
├── helpers.py                          151L
├── _core_helpers.py                    128L
├── orchestration_helpers.py            226L
├── async_dispatch.py                   203L
├── resolution.py                       383L   — Model/provider resolution
├── execution.py                        294L   — Execution coordination
├── core.py                             193L
├── work_context.py                     80L
├── estimate_endpoint.py                36L
└── (other minor files)
```

---

## 2. ProviderAdapter base class

**File:** `backend/app/adapters/base.py:1–169`

```python
class ProviderAdapter(ABC):
    """Protocol for AI provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Default: wrap complete() and yield single event."""
        ...

    async def start_tool_session(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> ProviderRuntimeSession:
        """Default: wrap complete_with_tool_events() in StreamBackedRuntimeSession."""
        ...
```

**Five methods** (one property + four async methods). Two are abstract (`complete`, `health_check`); three are default-implemented (`provider_name` property defined per-class; `stream` wraps `complete`; `start_tool_session` wraps `complete_with_tool_events`).

**Implicit "optional" methods** (looked up via `getattr()` rather than declared):
- `complete_with_tool_events(...)` → yields `tuple[ToolEvent, session_id | None]` for tool-loop integration
- `complete_with_tools(...)` → yields raw SDK messages for tool calling

**Method semantic mismatch:** `stream()` yields `StreamEvent` (single canonical type), but `complete_with_tool_events()` yields `ToolEvent` (different canonical type — defined in `gemini_events.py`!). Two parallel streaming abstractions.

---

## 3. Per-provider adapter inventory

### Claude (18 files, ~3,362 LOC) — biggest single sprawl

**Main:** `claude.py` (210L) — `ClaudeAdapter(ClaudeToolSessionMixin, ProviderAdapter)`
- Provider name: `"claude"`
- Overrides: `complete`, `stream`, `health_check`, `complete_with_tool_events`, `complete_with_tools`
- Routing: CLI when available; falls back to direct API (OAuth > API key)

**Direct API:**
- `claude_direct.py` (481L) — `complete_direct()`, `stream_direct()`, `sanitize_content()`, `convert_messages()`, `apply_cache_control()`, `resolve_direct_credentials()`
  - **NON-STREAMING:** `await client.messages.create(...)` at ~line 324 (the path that triggered the `820670c8` regression)
- `claude_oauth.py` (171L) — `complete_oauth()`, `_ensure_valid_oauth_token()`, `_refresh_oauth_token()`
- `claude_streaming.py` (252L) — `stream_oauth()`, streaming event handling
- `claude_auth.py` (196L) — CLI OAuth init + token storage

**Tool support (CLI path):**
- `claude_tools_helpers.py` (275L) — `complete_with_tools()`, tool result handling
- `claude_tool_events.py` (178L) — `adapt_claude_stream()` — Claude SDK → canonical ToolEvent
- `claude_tools_stream.py` (217L) — streaming tool loops
- `claude_tools_mcp.py` (92L)
- `claude_tools_permissions.py` (90L)
- `claude_tools_query_session.py` (309L)

**Mixin & infrastructure:**
- `_claude_tool_session.py` (133L) — `ClaudeToolSessionMixin` with `complete_with_tools` + `complete_with_tool_events`
- `_claude_sdk_builder.py` (164L)
- `_claude_settings.py` (184L)
- `_claude_constants.py` (73L)
- `_claude_json_utils.py` (78L)
- `_claude_result_metadata.py` (59L)
- `claude_utils.py` (164L)

**Pi-mono equivalent:** `providers/anthropic.ts` (1207L, single file) + `utils/oauth/anthropic.ts` (402L) = 1609L in 2 files. **agent-hub: 18 files / ~3362L. Sprawl ratio: 9× files, 2.1× LOC.**

### CodeX (3 files, ~1,300 LOC) — also Anthropic SDK OAuth

**`codex_oauth.py` (635L) — largest single file in adapters/**
- `CodexOAuthAdapter(ProviderAdapter)`
- Provider name: `"codex"`
- Overrides: `complete`, `stream`, `health_check`, `complete_with_tool_events`
- **NON-STREAMING:** `await client.messages.create(...)` around line 450+ (multiple sites)

**`codex_auth.py` (289L) — OAuth token management** (parallel to `claude_auth.py`)
**`codex_sse.py` (343L) — SSE streaming** (parallel to `claude_streaming.py`)
**`codex_token_cache.py` (72L)** (parallel to `_claude_*` config files)

**Note:** Codex is the legacy name for the Claude SDK OAuth path; this entire 3-file tree duplicates what `claude_*` already does. Convergence target: collapse Codex + claude_* into a single Anthropic provider matching `pi-mono/providers/anthropic.ts`.

### Gemini (13 files, ~1,678 LOC)

**Main:** `gemini.py` (183L) — `GeminiAdapter(ProviderAdapter)`
- Provider name: `"gemini"`
- Overrides: `complete`, `stream`, `health_check`, `start_tool_session`
- Multi-key failover

**Operations:**
- `gemini_adapter_ops.py` (126L) — `sdk_complete_with_failover()`, `sdk_health_check()`, `tool_loop()`
  - **NON-STREAMING:** `client.generate_content(request, stream=False)` at ~line 60+
- `gemini_adapter_stream.py` (214L) — `sdk_stream_with_failover()`

**Tool support:**
- `gemini_tools.py` (249L) — `call_tool()`, tool result handling
- `gemini_messages.py` (112L) — Message conversion
- `gemini_response.py` (173L) — Response parsing
- `gemini_events.py` (50L) — **defines `ToolEvent`, `ToolContentBlock`, `ToolMessage` — the canonical types live HERE** (smoking gun)

**Other:**
- `gemini_errors.py` (205L)
- `gemini_thinking.py` (56L)
- `gemini_image.py` (175L) (out of scope)
- `gemini_config.py` (96L)
- `gemini_utils.py` (166L)
- `gemini_adapter_settings.py` (13L) — stub

**Pi-mono equivalent:** `providers/google.ts` (501L, single file) + `providers/google-shared.ts` (350L) = 851L in 2 files. **agent-hub: 13 files / ~1678L. Sprawl ratio: 6.5× files, 2.0× LOC.**

### OpenAI-compatible family

**Base:** `openai_compat.py` (191L) — `OpenAICompatibleAdapter(ProviderAdapter)`
- Overrides: `complete`, `stream`, `health_check`
- Subclasses: `XAIAdapter`, `OpenRouterAdapter`, `OpenAIAdapter`, (Codex was once a subclass; now separate)

**Helpers:** `_openai_compat_helpers.py` (406L) — `is_auth_error()`, `handle_provider_error()`, `normalize_responses_content()`

**Providers (one file each):**
- `openai.py` (24L) — stub
- `xai.py` (293L) — XAIAdapter
- `openrouter.py` (63L) — OpenRouterAdapter

**Tool support:**
- `openai_tool_events.py` (147L) — event adaptation
- `_openai_tool_loop.py` (88L) — tool loop

**Pi-mono equivalent:** `providers/openai-completions.ts` (1148L, single file). **agent-hub: 7 files / ~1212L. Sprawl ratio: 7×, 1.1× LOC.**

### Kimi (1 file, 351 LOC)

**`kimi_code.py` (351L) — KimiCodeAdapter(ProviderAdapter)**
- Direct API client
- **NON-STREAMING:** `complete_with_tools` uses direct non-streaming `client.chat.completions` around line 150+ (the path that surfaced the `820670c8` regression)

### Stub adapters (5 files, ~143 LOC)

`moonshot.py`, `deepseek.py`, `zhipu.py`, `nvidia.py`, `minimax.py`, `local.py` — 22–41L each. Mostly placeholders inheriting `ProviderAdapter`.

### Cloudflare text (1 file, 92 LOC)

`cloudflare.py` — `CloudflareAdapter`. HTTP POST to Cloudflare Workers AI.

### Image adapters (OUT OF SCOPE per task)

`image_base.py`, `cloudflare_image.py`, `nvidia_image.py`, `minimax_image.py`, `gemini_image.py` — out of refactor scope.

### Non-streaming code paths (summary)

| File | Line(s) | Path |
|------|---------|------|
| `claude_direct.py` | ~324, `_create_with_temperature_retry` | `await client.messages.create(...)` (non-streaming) — patched in `b7517196` |
| `claude_tools_stream.py` | ~55+ | tool result appending pre-streaming |
| `codex_oauth.py` | ~450+ | `await client.messages.create(...)` |
| `gemini_adapter_ops.py` | ~60+ | `client.generate_content(request, stream=False)` |
| `kimi_code.py` | ~150+ | non-streaming `client.chat.completions.create` |
| `xai.py` | ~96+ | non-streaming Responses API |

**Pi-mono has ZERO non-streaming code paths.** Every provider emits an event stream; `complete()` is `stream().result()`. Every non-streaming site above is a convergence-time deletion.

---

## 4. Type sprawl

### `CompletionResult` — defined in 4 places

#### Site 1: `backend/app/adapters/types.py:48`
```python
@dataclass
class CompletionResult:
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None
    raw_response: Any = None
    cache_metrics: CacheMetrics | None = None
    tool_calls: list[ToolCallResult] | None = None
    container: ContainerState | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    fallback_reason: str | None = None
```
Adapter output (minimal).

#### Site 2: `backend/app/services/agent_routing_models.py:32`
```python
@dataclass
class CompletionResult:
    """Result of completion with fallback."""
    result: Any                          # Adapter result
    model_used: str
    used_fallback: bool
    fallback_reason: str | None = None
```
Services-layer wrapper for fallback tracking. **Same name, completely different shape.**

#### Site 3: `backend/app/workflows/completion.py:56`
```python
class CompletionResult(BaseModel):
    """Pydantic model for Hatchet workflow serialization."""
    task_id: str
    content: str = ""
    model: str = "unknown"
    provider: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    session_id: str = ""
    memory_uuids: list[str] = Field(default_factory=list)
    cited_uuids: list[str] = Field(default_factory=list)
    from_cache: bool = False
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[dict[str, Any]] = Field(default_factory=list)
```
Pydantic for Hatchet serialization. **Third definition.**

#### Site 4: `backend/app/api/complete/types.py:12`
```python
@dataclass
class CompletionInternalResult:
    """Result from complete_internal() for completion operations."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    session_id: str
    memory_uuids: list[str]
    cited_uuids: list[str]
    from_cache: bool = False
    cache_metrics: Any | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)
    error_summary: dict[str, Any] | None = None
    model_used: str | None = None
    fallback_used: bool = False
    requested_model: str | None = None
    requested_provider: str | None = None
    fallback_reason: str | None = None
```
24-field "internal" variant. **Named differently but structurally a fourth CompletionResult.**

### `ToolExecutionResult` — `backend/app/api/complete/tool_models.py:23`

Identical to `CompletionInternalResult` except adds `tool_result_summaries: list[str] = field(default_factory=list)`. **Should not exist as a separate type.**

### `_ExecutionState` — `backend/app/api/complete/tool_handler_utils.py:42`
```python
@dataclass
class _ExecutionState:
    """Shared mutable state for a tool execution run."""
    agent_slug: str | None
    messages_for_adapter: list[Message]
    external_id: str | None = None
    requires_progress_tags: bool = False
    content_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    tool_result_summaries: list[str] = field(default_factory=list)
    tool_calls_count: int = 0
    turn: int = 0
    event_turn: int = 0
    awaiting_tool_results: bool = False
    terminal_finish_reason: str | None = None
    last_tool_result_signature: tuple[str, str, str] | None = None
    repeated_tool_result_count: int = 0
```
Pi-mono has nothing like this. The state belongs inside the tool loop, not as a 13-field shared mutable state object.

### `StreamEvent` — `backend/app/adapters/types.py:20`
```python
@dataclass
class StreamEvent:
    type: Literal["content", "done", "error", "thinking", "tool_use", "tool_result", "turn_start", "turn_end"]
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    thinking_tokens: int | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    is_error: bool = False
    duration_ms: int | None = None
    thought_signature: str | None = None
    turn: int | None = None
```
**8 event variants** in a flat dataclass. Pi-mono's `AssistantMessageEvent` has **12 variants** as a discriminated union with per-variant fields. The flat-dataclass shape forces every consumer to know which fields apply to which type — pi-mono's discriminated union makes that a type error.

### `ToolEvent` — `backend/app/adapters/gemini_events.py:31` (defined in Gemini adapter!)
```python
@dataclass
class ToolEvent:
    """Unified event for tool integration pipeline."""
    type: str                            # "assistant", "tool_result", "result", "error"
    subtype: str | None = None
    message: ToolMessage | None = None
    content: str = ""
    tool_use_id: str | None = None
    is_error: bool = False
    result: str = ""
    error: str = ""
    duration_ms: int | None = None
    finish_reason: str | None = None

@dataclass
class ToolContentBlock:
    type: str
    text: str = ""
    name: str = ""
    input: dict[str, Any] | None = None
    id: str = ""

@dataclass
class ToolMessage:
    content: list[ToolContentBlock]
```
**Canonical tool-loop event type lives inside the Gemini adapter file.** Imported by Claude, Codex, OpenAI tool-event modules. This is the most obviously misplaced type in the codebase.

### `ToolResult` — `backend/app/services/tools/base.py:59`
```python
@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_use_id: str
    content: str
    is_error: bool = False
    duration_ms: int | None = None
```

### `ToolResultPayload` — `backend/app/adapters/tool_result_payload.py:10`
```python
@dataclass(frozen=True)
class ToolResultPayload:
    content: str
    is_error: bool = False
    duration_ms: int | None = None
```
Differs from `ToolResult` only by being frozen and lacking `tool_use_id`. Wrapper-only type.

### `AgentProgress` / `AgentProgressInfo` — 2 nearly-identical definitions

**Site 1:** `backend/app/api/complete/tool_models.py:10`
```python
@dataclass
class AgentProgress:
    turn: int
    status: str
    message: str
    topic: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None
```

**Site 2:** `backend/app/api/orchestration_models.py:424`
```python
class AgentProgressInfo(BaseModel):
    """Progress update from agentic execution."""
    turn: int
    status: str
    message: str
    topic: str | None = None
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking: str | None = None
```
Same fields. Different name. Different base (dataclass vs Pydantic). One for internal use, one for HTTP response.

### `RuntimeSession` — `backend/app/adapters/runtime_session.py:11`
```python
class ProviderRuntimeSession(ABC):
    """Canonical provider runtime session boundary for one active turn."""

    @abstractmethod
    def events(self) -> AsyncIterator[tuple[Any, str | None]]: ...

    async def interrupt(self) -> None: ...

    async def respond_to_request(
        self, *, request_id: str, decision: str, payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def respond_to_user_input(
        self, *, request_id: str, response: str,
    ) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
```
Implementation: `StreamBackedRuntimeSession` (line 50). Wraps `AsyncIterator` with interrupt/close callbacks.

**Pi-mono has NO equivalent.** Pi-mono's stream IS the session boundary — the AsyncIterator IS the runtime, and consumers cancel via `StreamOptions.signal: AbortSignal`. No `ProviderRuntimeSession` class needed.

### `RuntimeSessionRegistry` — `backend/app/api/complete/runtime_session_registry.py:17`
```python
class RuntimeSessionRegistry:
    """Registry mapping session_id → ProviderRuntimeSession."""
```
Tracks active agentic sessions per request context.

---

## 5. `backend/app/api/complete/` — pipeline sprawl

### Tool-loop pipelines (SYNCHRONOUS path)

| File | Public function | Role |
|------|-----------------|------|
| `tool_handlers.py` (205L) | `async def _complete_with_tools(db, session, model, provider, messages, tools, working_dir, max_turns, project_id, session_id, agent_slug, tool_catalog, temperature, skip_cache, cache, loaded_memory_uuids, memory_group_id, user_messages_for_db) -> ToolExecutionResult` | Unified entry to sync tool handling |
| `tool_handler_utils.py` (301L) | `_init_execution_state()`, `_run_tool_loop()` | Core loop driving turn iteration |
| `multi_turn_executor.py` (139L) | `async def run_multi_turn_completion(cfg: TurnLoopConfig) -> ToolExecutionResult` | Turn iteration |
| `multi_turn_loop.py` (172L) | `async def execute_single_turn(cfg, turn, state, container_manager) -> bool` | Per-turn adapter call |
| `multi_turn_helpers.py` (238L) | `TurnLoopConfig`, `process_turn_result()` | Config + result processing |

**Five files** doing what pi-mono does in **zero files** (the tool loop is the *caller's* job, not the adapter's).

### Tool-loop pipelines (STREAMING path) — parallel to the sync path

| File | Public function | Role |
|------|-----------------|------|
| `streaming_tool_loop.py` (156L) | `async def iter_stream_sse_with_tools(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx, tools, project_id, max_tool_turns) -> AsyncIterator[str]` | Streaming entry |
| `streaming_tool_executor.py` (171L) | `collect_turn_events()`, `iter_unresolved_tools()`, `append_turn_messages()` | Tool event collection per turn |
| `streaming_tool_messages.py` (102L) | `sse_for_simple_event()` | SSE chunk building |
| `streaming_runtime_session.py` (415L) | `iter_runtime_session_sse_with_tools()` | Alt path via ProviderRuntimeSession |

**Four more files** for the streaming variant of the same loop. Pi-mono has one shape for both.

### Streaming infrastructure

| File | Role |
|------|------|
| `streaming.py` (205L) | `orchestrate_streaming()` entry |
| `streaming_handlers.py` (313L) | Tool-loop streaming handlers |
| `streaming_context.py` (135L) | `StreamContext` (async-task-local session state) |
| `streaming_persistence.py` (411L) | SSE building + stream progress publishing |

### Session abstractions

| File | Public surface | Role |
|------|---------------|------|
| `session_manager.py` (198L) | `async def get_or_create_session(db, session_id, project_id, provider, model, session_type, external_id, client_id, request_source, agent_slug, current_branch, working_dir, parent_session_id, requested_provider, requested_model, trace_id) -> tuple[DBSession, list[Message], bool]` | Session lookup/creation |
| `_session_helpers.py` (162L) | `load_session()`, `maybe_reset_persona_session()` | Session loading helpers |
| `session_setup.py` (110L) | `setup_session_storage()` | Session persistence config |
| `runtime_session_registry.py` (43L) | `RuntimeSessionRegistry` class | Active-session map |

**Four files** for what pi-mono treats as **the caller's database concern** (pi-mono just receives `messages: Message[]` on each call).

### HTTP entrypoints

**`endpoints.py` (69L):**

| Route | Method | Body schema | Response | Stream? |
|-------|--------|-------------|----------|---------|
| `/complete` | POST | `CompletionRequest` | `CompletionResponse \| StreamingResponse \| JSONResponse` | When `request.stream=True` |
| `/complete/cancel` | POST | `CancelStreamRequest{session_id}` | `dict[str, object]` | No |
| `/estimate` | POST | `EstimateRequest` | `EstimateResponse` | No |

**`async_endpoints.py` (133L):**

| Route | Method | Path param | Response |
|-------|--------|------------|----------|
| `/complete/tasks/{task_id}` | GET | `task_id: str` | `AsyncTaskStatusResponse` |
| `/complete/tasks/{task_id}/cancel` | DELETE | `task_id: str` | `dict[str, str]` |

### Top-level orchestration

| File | Public function | Branches |
|------|-----------------|----------|
| `complete_orchestrator.py` (188L) | `orchestrate_completion()` | `stream=True` → `orchestrate_streaming()`; else `complete_internal()` |
| `complete_execution.py` (221L) | `complete_internal()` | Calls `get_or_create_session()` → `_complete_with_tools()` if tools, else `adapter.complete()` |

### Tool execution support (10 files)

`tool_event_processor.py` (297L), `tool_event_storage.py` (152L), `tool_models.py` (53L), `tool_progress.py` (115L), `tool_provisioner.py` (187L), `tool_response_finalizer.py` (221L), `tool_result_builder.py` (146L), `tool_router.py` (93L), `tool_handler_utils.py` (301L), `tool_handlers.py` (205L). Roles include tool catalog provisioning, progress tracking, result persistence, response finalization, tool routing.

### Advanced features (9 files)

`context_compaction.py`, `cache_handler.py`, `citation_tracker.py`, `_citation_helpers.py`, `memory_handler.py`, `finish_reason_handler.py`, `precision_search_guidance.py`, `closeout_policy.py`, `turn_processor.py`, `turn_processor_helpers.py`, `turn_budget.py`, `error_summary.py`.

These are **not adapter concerns** — they're orchestration/memory/UI concerns that have leaked into the completion pipeline. Pi-mono has none of these (memory, citations, search guidance, closeout policy are all the caller's job).

### Observability + helpers (14 files)

`execution_observability.py`, `handlers.py`, `handler_helpers.py`, `error_handlers.py`, `event_helpers.py`, `helpers.py`, `_core_helpers.py`, `orchestration_helpers.py`, `async_dispatch.py`, `async_endpoints.py`, `resolution.py`, `execution.py`, `core.py`, `work_context.py`. Many of these are split helpers ("X_helpers.py") next to their consumer — a 2024 stylistic pattern.

---

## 6. Cross-references — types re-exported outside the two directories

```
backend/app/services/agent_routing_models.py:32    class CompletionResult       (4th definition)
backend/app/workflows/completion.py:56             class CompletionResult       (3rd definition)
backend/app/api/orchestration_models.py:424        class AgentProgressInfo      (2nd progress type)
backend/app/api/persona/schema_stream.py:10        class PersonaStreamEventPreview  (unrelated)
```

**`adapters/base.py` re-exports** (from `adapters/types.py`): `CompletionResult`, `StreamEvent`, `Message`, `CacheMetrics`, `ToolCallResult`, `ContainerState`.

**`api/complete/__init__.py` re-exports** tool-loop entry points, schemas, types.

---

## 7. Counts table

### Top-line totals

| Surface | Files | LOC |
|---------|------:|----:|
| `backend/app/adapters/` | 67 | 10,412 |
| `backend/app/api/complete/` | 66 | 11,423 |
| **TOTAL in scope** | **133** | **21,835** |

### Per-provider breakdown (adapters/)

| Provider | Files | LOC | Pi-mono equivalent | Pi-mono LOC | File ratio | LOC ratio |
|----------|------:|----:|--------------------|------------:|-----------:|----------:|
| Claude (`claude*`, `_claude*`) | 18 | ~3,362 | `anthropic.ts` + oauth | 1,646 | **9.0×** | 2.0× |
| Gemini (`gemini*`) | 13 | ~1,678 | `google.ts` + `google-shared.ts` | 851 | **6.5×** | 2.0× |
| Codex (`codex*`) | 3 | ~1,300 | (same `anthropic.ts`) | (incl. above) | — | — |
| OpenAI-compat (`openai_compat`, `openai`, `xai`, `openrouter` + helpers) | 7 | ~1,212 | `openai-completions.ts` | 1,148 | **7.0×** | 1.1× |
| Kimi | 1 | 351 | (would share `openai-completions.ts`) | — | — | — |
| Stubs (moonshot, deepseek, zhipu, nvidia, minimax, local) | 6 | ~143 | (would share `openai-completions.ts`) | — | — | — |
| Cloudflare text | 1 | 92 | helper only in pi-mono | 35 | — | — |
| Core (`base`, `types`, `runtime_session`, `registry`, `errors`, etc.) | 11 | ~1,950 | `api-registry.ts` + `types.ts` + `stream.ts` + helpers | ~870 | — | 2.2× |
| Image (out of scope) | 4 | ~644 | (out of scope) | — | — | — |
| **TOTAL** | **67** | **10,412** | (~42 files in pi-mono in-scope) | **12,624** | — | — |

### Per-pipeline breakdown (api/complete/)

| Pipeline / Area | Files | LOC | Pi-mono equivalent |
|-----------------|------:|----:|--------------------|
| Tool loops (sync: tool_handlers, tool_handler_utils, multi_turn_*) | 5 | ~1,055 | none — caller concern |
| Tool loops (streaming: streaming_tool_*) | 4 | ~844 | none — caller concern |
| Streaming infra (streaming, streaming_handlers, streaming_context, streaming_persistence) | 4 | ~1,064 | `utils/event-stream.ts` (87L) |
| Sessions (session_manager, session_setup, _session_helpers, runtime_session_registry) | 4 | ~513 | none — caller concern |
| Request/response schemas + setup | 7 | ~1,084 | partial — `types.ts` covers request shape via `Context` |
| Orchestration (complete_orchestrator, complete_execution, agent_loop, resolution) | 4 | ~1,035 | none — caller concern |
| Advanced features (cache, memory, citation, context_compaction, closeout_policy, etc.) | 12 | ~2,000 | none — caller concern |
| Observability + helpers | 14 | ~1,866 | minimal `utils/diagnostics.ts` (45L) |
| Tool support (event_processor, provisioner, router, etc.) | 10 | ~1,471 | none — caller concern |
| Endpoints (endpoints, async_endpoints, estimate_endpoint) | 3 | ~238 | none — pi-mono is a library, not a service |
| **TOTAL** | **66** | **11,423** | **~87L** (the `utils/event-stream.ts` + small bits) |

**Pi-mono target for the in-scope hand-written surface: ~42 files / ~12,624 LOC. Agent-hub current: ~133 files / ~21,835 LOC. Ratio: 3.2× files, 1.7× LOC.**

---

## 8. Smoking guns / theatre

### Critical (must address in convergence)

1. **`CompletionResult` defined 4 times** with 3 different shapes (Site 1 / Site 3 / Site 4 share a family, Site 2 is a fallback wrapper). Site 4 has 24 fields. **Pi-mono has one shape: `AssistantMessage`.**

2. **`ToolExecutionResult` ≈ `CompletionInternalResult` + 1 field.** No reason to be separate types.

3. **`ToolEvent` (canonical tool-loop event) defined inside `gemini_events.py`.** Cross-imported by Claude/Codex/OpenAI tool modules. **Should be in `types.py` (or removed entirely — pi-mono doesn't have a separate ToolEvent; tool calls are content blocks in `AssistantMessage`).**

4. **Non-streaming code paths in claude_direct, codex_oauth, gemini_adapter_ops, kimi_code, xai.** Every one of these is the kind of path that produced the `820670c8` regression. **Pi-mono has zero of these.**

5. **Two parallel streaming abstractions:** `stream()` (yields `StreamEvent`) AND `complete_with_tool_events()` (yields `ToolEvent`). One adapter class has both. Pi-mono has one stream type.

6. **Two parallel tool-loop pipelines:** sync (`tool_handlers.py` + `multi_turn_*`) AND streaming (`streaming_tool_*`). Each has its own state machine and result type. Pi-mono has none — tool loops are caller-side.

7. **Two parallel session abstractions:** DB `Session` (via `session_manager`) AND `ProviderRuntimeSession` (via `runtime_session.py`). Pi-mono has neither.

### Moderate

8. **`closeout_policy.py` (259L)** — tool-loop recovery state machine. Lots of accumulated heuristics. Pi-mono has no closeout policy; stop reasons are flat (`stop | length | toolUse | error | aborted`).

9. **`precision_search_guidance.py` (256L)** — search guidance injection. Not an adapter concern.

10. **`citation_tracker.py` + `_citation_helpers.py` (421L)** — citation tracking from memory. Not an adapter concern.

11. **`StreamContext` thread-local hack** (`streaming_context.py:135L`) — uses async-task contextvars; `@classmethod current()` for implicit retrieval. Pi-mono passes context explicitly.

12. **Three files touching routing** (`adapters/registry.py`, `api/complete/resolution.py`, `services/agent_routing_models.py`). Hard to audit consistency.

13. **18 claude_* files for ONE provider.** This is the single most visible sprawl. Pi-mono's anthropic provider is one 1207L file plus shared transform-messages.ts and oauth.

14. **`event_stream.py` (`StreamFromComplete` adapter)** — complete()→stream() bridge. Some providers may rely on this; if all providers had native streaming, this could be deleted.

15. **Test doubles tolerated in production code** (`request_setup.py:85` — "tolerating legacy test doubles"). Removable when test setup is cleaned up.

### Minor

16. Comments referring to `task-XXXXXXXX` IDs scattered through code (residue from past task-driven refactors).

17. `_session_helpers.py`, `_core_helpers.py`, `tool_handler_utils.py`, `tool_progress.py`, `turn_processor_helpers.py`, `event_helpers.py`, `orchestration_helpers.py` — all the "X_helpers" / "_X" files are a 2024-era split-by-style pattern.

18. `_errors_types.py` + `_errors_retry_delay.py` — splits inside `adapters/` mirror the helper pattern.

---

## 9. Recent commits affecting this surface (last 30)

```
b7517196  Stream Anthropic adapter tool loops to satisfy SDK long-request guard
820670c8  Drive adapter max_tokens from catalog and lift tool-loop turn ceilings
c86f926f  Remove 240s default timeout from agentic model turns
773dc973  Timeout agentic model turns for fallback
6036c5f7  fix: stop repeated tool result loops
d42db71b  wip(task-7c27e1a1): recover prior shared-checkout changes
e3671a12  Stabilize agent runtime cancellation
11f5767c  Enable adaptive model auto routing
dac040d5  Fix Agent Hub model pages, memory analytics, and tool safety
5ce11e85  Optimize Work Chats routing context
db963140  Add adhoc WorkSpec model routing
8665fb6b  Simplify Agent Hub project tool tiers
dc36d274  publish project work
63cb7174  Expand work chat routing and persona tool controls
41e43ca2  Moved runtime-session streaming tool handling out of streaming_tool_loop.py into streaming_runtime_session.py
cf3488a0  Collapse persona operator tool surface to core tiered tools
dc37be6b  Implement SummitFlow Work Chats
3d5d961c  Implemented Agent Hub scratch context tools
607b5efb  refactor codex oauth adapter
1645b9b9  Use all Gemini keys for tool loops
38352c76  Accept heartbeat closeouts with progress tags
df627778  Accept heartbeat summary-only closeouts
f1864d7e  fix(codex): reject expired local auth fallback
a877fb92  fix(codex): recover local auth after refresh token reuse
0b4aca40  fix: restore persona tool surface in read-tier sessions
ae82001d  test(backend): 85 files changed, 627 insertions(+), 1741 deletions(-)
d501d79f  feat(models): add Claude Opus 4.7 model support
337f848e  Honor use_memory in agentic completion dispatch
a83e0aea  ship persona operator workspace on main
0ee8d032  feat(models): add catalog sync state and tighten runtime routing
```

**Signals:**
- Tool loops are in active flux (timeout tuning, cancellation, repeated-result fix, refactors of streaming tool-loop, multi-turn turn-ceiling changes).
- Several "while we're here" commits (Work Chats, persona, memory analytics) are landing in completion pipeline files.
- Recent runtime-session extraction (`41e43ca2`) shows internal attempt at modularization — the right direction, but stops short of pi-mono's full collapse.
- `607b5efb` refactor codex oauth — Codex is being touched in isolation, perpetuating the duplication with claude_*.
- `820670c8` (raised max_tokens, triggered non-streaming guard) and `b7517196` (tactical fix forcing streaming) are the exact regressions cited in the task description.
