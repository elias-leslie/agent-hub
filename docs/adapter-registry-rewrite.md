# Agent Hub Adapter Registry Rewrite

**Status**: Research / Planning
**Date**: 2026-02-20
**Reference**: pi-mono at `/home/kasadis/references/pi-mono/packages/ai/src/`

---

## Problem Statement

Agent Hub's adapter layer has grown to 36 files / 6,517 lines across 6 provider families. Key issues:

- **Message conversion**: 4 separate implementations
- **Tool calling loops**: 3 separate implementations (Claude, Gemini, OpenAI-compatible)
- **Tool event processors**: 2 duplicated processors (`tool_claude_processor.py`, `tool_gemini_processor.py`)
- **CloudCode client**: duplicated between Gemini OAuth and CloudCode Claude
- **Hard-coded routing**: `tool_router.py` branches on `if provider == "claude"` / `elif provider == "gemini"`
- **No cross-provider message replay**: switching models mid-conversation loses thinking blocks, tool IDs break

Pi-mono handles 15+ providers in ~6,800 lines using a registry + strategy pattern.

---

## Current Architecture

```
ProviderAdapter (abstract base in base.py)
    |
    +-- ClaudeAdapter -------> 7 files, 1,199 lines
    |   - Dual-mode: CLI subprocess (Claude Agent SDK) + direct OAuth API
    |   - CLI path: claude_oauth.py, claude_streaming.py, claude_tools.py,
    |     claude_tools_helpers.py, claude_utils.py
    |   - Tool calling: SDK yields AssistantMessage/UserMessage/ToolUseBlock/ToolResultBlock
    |   - Processor: tool_claude_processor.py
    |
    +-- GeminiAdapter -------> 13 files, 2,588 lines (LARGEST)
    |   - Dual-mode: API key/ADC + CloudCode OAuth
    |   - OAuth path: gemini_cloudcode.py (765 lines, mixed concerns)
    |   - Tool calling: gemini_tools.py yields MockEvents
    |   - Processor: tool_gemini_processor.py
    |   - Module-level mutable state (_auth_preference global)
    |
    +-- CloudCodeClaudeAdapter -> 3 files, 595 lines
    |   - Uses Gemini's CloudCodeClient for Claude via Antigravity
    |   - Shares gemini_cloudcode.py but no shared base class
    |
    +-- CodexOAuthAdapter ----> 3 files, 807 lines
    |   - Raw HTTP + SSE to ChatGPT backend
    |   - File-locked token refresh
    |   - No tool calling support
    |
    +-- OpenAICompatibleAdapter -> 6 files, 610 lines (CLEANEST)
        - Base class with 5 tiny concrete adapters (22-66 lines each)
        - OpenAI, OpenRouter, xAI, Minimax, Zhipu
        - Tool calling: inline loop yielding StreamEvents
```

### Current Tool Calling Flow

```
tool_router.route_tool_execution()
    |
    +-- if provider == "claude":
    |   ClaudeAdapter() -> _complete_with_claude_tools()
    |       -> _run_claude_tool_loop()
    |           -> adapter.complete_with_tools()
    |               -> claude_agent_sdk.query()  [subprocess]
    |           -> process_claude_message()  [per-message DB storage]
    |
    +-- elif provider == "gemini":
        GeminiAdapter() -> _complete_with_gemini_tools()
            -> _run_gemini_tool_loop()
                -> adapter.complete_with_tools()
                    -> gemini_tools.execute_tool_loop()  [HTTP API loop]
                -> process_gemini_event()  [per-event DB storage]
```

### Current File Inventory

**Base / Shared** (4 files, 721 lines):
- `base.py` - ProviderAdapter ABC, ProviderError
- `types.py` - Message, StreamEvent, CompletionResult, CacheMetrics, ToolCallResult
- `errors.py` - Error types, retry decorator
- `helpers_adapters.py` - Factory dict, get_adapter()

**Claude** (7 files, 1,199 lines):
- `claude.py` - Main adapter, dual-mode routing
- `claude_oauth.py` - CLI path completion via SDK
- `claude_streaming.py` - CLI path streaming via SDK
- `claude_tools.py` - Tool calling via SDK query()
- `claude_tools_helpers.py` - SDK option builder, permission checker
- `claude_utils.py` - Prompt building, permission config parsing
- `claude_auth.py` - OAuth token refresh

**Gemini** (13 files, 2,588 lines):
- `gemini.py` - Main adapter, auth mode selection
- `gemini_cloudcode.py` - CloudCode OAuth client (765 lines!)
- `gemini_tools.py` - API key tool loop
- `gemini_convert.py` - Message format conversion
- `gemini_streaming.py` - SSE stream parsing
- `gemini_auth.py` - OAuth credential management
- `gemini_helpers.py` - Misc helpers
- Plus 6 more helper files

**CloudCode Claude** (3 files, 595 lines):
- `cloudcode_claude.py` - Adapter using Gemini's CloudCode client
- `cloudcode_claude_helpers.py` - Message/tool conversion
- `cloudcode_claude_auth.py` - Antigravity credential fallback

**Codex OAuth** (3 files, 807 lines):
- `codex_oauth.py` - Main adapter
- `codex_auth.py` - Token refresh with file locking
- `codex_helpers.py` - SSE parsing, response conversion

**OpenAI-Compatible** (6 files, 610 lines):
- `openai_compat.py` - Base class (259 lines)
- `_openai_compat_helpers.py` - Shared helpers
- `openai.py`, `openrouter.py`, `xai.py`, `minimax.py`, `zhipu.py` - Concrete (22-66 lines each)

---

## Target Architecture (Pi-mono Pattern)

### Core Concept

Replace class hierarchy with a registry of provider implementations. Each provider exports functions conforming to a shared interface. All providers emit the same event stream type.

```
registry.py  <-- register(name, stream, complete, convert_messages, convert_tools)
    |
    +-- providers/
    |   +-- anthropic.py       (direct API)
    |   +-- claude_sdk.py      (CLI subprocess via Agent SDK)
    |   +-- gemini.py          (API key / ADC)
    |   +-- cloudcode.py       (shared OAuth client for Gemini + Claude)
    |   +-- openai_compat.py   (base for OpenAI-compatible)
    |   +-- codex.py           (ChatGPT backend)
    |   +-- openrouter.py, xai.py, minimax.py, zhipu.py  (tiny)
    |
    +-- types.py               (unified Message, StreamEvent, Tool, Context)
    +-- convert.py             (cross-provider message transformation)
    +-- tool_executor.py       (single generic tool loop for ALL providers)
    +-- event_stream.py        (async event stream abstraction)
```

### Layer 1: Unified Types

```python
# types.py — enhanced from current base

@dataclass
class ContentBlock:
    """Structured content within a message."""
    type: Literal["text", "image", "thinking", "tool_call", "tool_result"]
    text: str = ""
    # thinking fields
    thinking: str = ""
    thinking_signature: str | None = None
    # tool_call fields
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    # tool_result fields
    tool_output: str = ""
    is_error: bool = False
    # image fields
    mime_type: str = ""
    data: str = ""  # base64

@dataclass
class Message:
    role: Literal["user", "assistant", "system", "tool_result"]
    content: str | list[ContentBlock]
    # Provenance (for cross-provider replay)
    api: str | None = None
    provider: str | None = None
    model: str | None = None
    timestamp: float = 0.0

@dataclass
class Context:
    system_prompt: str | None = None
    messages: list[Message] = field(default_factory=list)
    tools: list[Tool] | None = None

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

# StreamEvent types — expanded from current 5 to cover tool lifecycle
@dataclass
class StreamEvent:
    type: Literal[
        "start",
        "text_delta", "text_end",
        "thinking_delta", "thinking_end",
        "toolcall_start", "toolcall_delta", "toolcall_end",
        "tool_result",
        "done", "error",
    ]
    content: str = ""
    content_index: int = 0
    # Final message (on "done")
    message: Message | None = None
    # Token usage (on "done")
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_metrics: CacheMetrics | None = None
    # Tool fields (on toolcall_* and tool_result)
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_output: str = ""
    is_error: bool = False
    duration_ms: int | None = None
    # Stop reason
    finish_reason: str | None = None
    error_message: str | None = None
```

### Layer 2: Provider Registry

```python
# registry.py

@dataclass
class ProviderImpl:
    name: str
    stream: Callable[[Model, Context, StreamOptions], AsyncIterator[StreamEvent]]
    complete: Callable[[Model, Context, StreamOptions], Awaitable[CompletionResult]] | None = None
    health_check: Callable[[], Awaitable[bool]] | None = None
    convert_messages: Callable[[list[Message], Model], list[dict]] | None = None
    convert_tools: Callable[[list[Tool]], list[dict]] | None = None

_registry: dict[str, ProviderImpl] = {}

def register(provider: ProviderImpl) -> None:
    _registry[provider.name] = provider

def get(name: str) -> ProviderImpl:
    if name not in _registry:
        raise ValueError(f"No provider registered: {name}")
    return _registry[name]

# complete() derived from stream() if not provided
async def complete(name: str, model: Model, context: Context, options: StreamOptions) -> CompletionResult:
    provider = get(name)
    if provider.complete:
        return await provider.complete(model, context, options)
    # Default: consume stream, return final result
    result = None
    async for event in provider.stream(model, context, options):
        if event.type == "done":
            result = _build_completion_result(event)
    return result
```

### Layer 3: Unified Tool Executor

```python
# tool_executor.py — replaces tool_router.py + tool_claude_processor.py + tool_gemini_processor.py

async def execute_with_tools(
    provider_name: str,
    model: str,
    context: Context,
    db: AsyncSession,
    session_id: str,
    max_turns: int = 10,
    **kwargs,
) -> ToolExecutionResult:
    """Generic tool execution loop for ALL providers.

    All providers emit the same StreamEvent types, so one processor handles everything.
    """
    provider = registry.get(provider_name)
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_count = 0
    turn = 0

    async for event in provider.stream(model, context, options):
        match event.type:
            case "text_delta":
                content_parts.append(event.content)
            case "thinking_delta":
                thinking_parts.append(event.content)
            case "toolcall_end":
                tool_calls_count += 1
                await store_tool_use(db, session_id, event.tool_name, event.tool_input)
                await tracker.report_tool_use(turn, event.tool_name, event.tool_input)
            case "tool_result":
                await store_tool_result(
                    db, session_id, event.tool_call_id, event.tool_output,
                    event.is_error, duration_ms=event.duration_ms,
                )
                turn += 1
            case "done":
                break
            case "error":
                raise ProviderError(event.error_message, provider=provider_name)

    return ToolExecutionResult(
        content="".join(content_parts),
        thinking_content="".join(thinking_parts),
        tool_calls_count=tool_calls_count,
        turns=turn,
    )
```

### Layer 4: Per-Provider Modules (examples)

```python
# providers/anthropic.py — direct Anthropic API

def convert_messages(messages: list[Message], model: Model) -> list[dict]:
    """Convert unified messages to Anthropic API format."""
    system_parts, api_messages = [], []
    for msg in transform_messages(messages, model):  # cross-provider cleanup
        if msg.role == "system":
            system_parts.append(msg.content)
        elif msg.role == "assistant":
            blocks = _convert_assistant_blocks(msg.content)
            api_messages.append({"role": "assistant", "content": blocks})
        elif msg.role == "tool_result":
            api_messages.append({"role": "user", "content": [_convert_tool_result(msg)]})
        else:
            api_messages.append({"role": "user", "content": msg.content})
    return system_parts, api_messages

def convert_tools(tools: list[Tool]) -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]

async def stream(model: Model, context: Context, options: StreamOptions) -> AsyncIterator[StreamEvent]:
    client = anthropic.AsyncAnthropic(api_key=_get_api_key())
    params = _build_params(model, context, options)
    async with client.messages.stream(**params) as s:
        async for event in s:
            yield _convert_event(event)  # Anthropic event -> unified StreamEvent

register(ProviderImpl(name="anthropic", stream=stream, convert_messages=convert_messages, ...))
```

```python
# providers/claude_sdk.py — Claude Agent SDK (subprocess)

async def stream(model: Model, context: Context, options: StreamOptions) -> AsyncIterator[StreamEvent]:
    """Wrap Claude Agent SDK's message types into unified StreamEvents."""
    from claude_agent_sdk import query, ClaudeAgentOptions
    sdk_opts = _build_sdk_options(model, options)
    prompt = _build_prompt(context)
    async for msg in query(prompt=prompt, options=sdk_opts):
        for event in _convert_sdk_message(msg):  # SDK message -> unified StreamEvent(s)
            yield event

def _convert_sdk_message(msg) -> list[StreamEvent]:
    """Convert one SDK message into one or more StreamEvents."""
    events = []
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                events.append(StreamEvent(type="text_delta", content=block.text))
            elif _is_tool_use_block(block):
                events.append(StreamEvent(
                    type="toolcall_end",
                    tool_call_id=block.id, tool_name=block.name, tool_input=block.input,
                ))
            elif _is_thinking_block(block):
                events.append(StreamEvent(type="thinking_delta", content=block.thinking))
    elif isinstance(msg, UserMessage):
        for block in msg.content:
            if hasattr(block, "tool_use_id"):
                events.append(StreamEvent(
                    type="tool_result",
                    tool_call_id=block.tool_use_id, tool_output=block.content,
                    is_error=block.is_error,
                ))
    return events

register(ProviderImpl(name="claude", stream=stream, ...))
```

### Layer 5: Cross-Provider Message Transformation

```python
# convert.py — inspired by pi-mono's transform-messages.ts

def transform_messages(messages: list[Message], target_model: Model) -> list[Message]:
    """Clean up messages for cross-provider replay.

    Handles:
    1. Thinking blocks: preserve with signatures if same model, convert to text otherwise
    2. Tool call IDs: normalize for target provider's constraints
    3. Orphaned tool calls: insert synthetic error results
    4. Errored messages: skip entirely (incomplete, cause API errors)
    """
    tool_call_id_map: dict[str, str] = {}
    result: list[Message] = []

    for msg in messages:
        if msg.role == "assistant":
            same_model = (msg.provider == target_model.provider and msg.model == target_model.id)
            transformed_content = _transform_assistant_content(msg.content, same_model, target_model)
            result.append(replace(msg, content=transformed_content))
        elif msg.role == "tool_result":
            # Remap tool_call_id if it was normalized
            result.append(_remap_tool_result(msg, tool_call_id_map))
        else:
            result.append(msg)

    return _insert_synthetic_tool_results(result)
```

---

## Benefits

| Benefit | Impact | Details |
|---------|--------|---------|
| **Single tool event processor** | Eliminates 3x bug-fix effort | One `tool_executor.py` replaces tool_claude_processor + tool_gemini_processor + OpenAI inline |
| **Adding new provider** | 1 file instead of class + helpers + processor | Just implement `stream()` + `convert_*()` + `register()` |
| **Cross-provider replay** | New capability | Switch models mid-conversation without losing context |
| **Code reduction** | ~40-50% (6,500 → 3,000-3,500 lines) | Gemini's 12-file sprawl collapses dramatically |
| **No hard-coded routing** | Extensible | `tool_router.py` becomes `registry.get(provider).stream()` |
| **Testable conversions** | Pure functions | `convert_messages()` and `convert_tools()` are easy to unit test |

## Pain Points

| Pain Point | Severity | Mitigation |
|------------|----------|------------|
| **Claude Agent SDK is a subprocess** | Medium | Adapter layer converts SDK types → StreamEvent. SDK still owns the agentic loop. |
| **Migration risk** | High | Phase the work. Feature-flag new registry alongside old adapters. |
| **Gemini CloudCode shared client** | Medium | Extract once into `providers/cloudcode_client.py`, used by both Gemini OAuth and CloudCode Claude |
| **Testing every path** | Medium | Need provider × method matrix. Current tests are sparse. |
| **2-3 week effort** | Medium | Phased approach reduces risk |

## Long-term Considerations

| Consideration | Assessment |
|---------------|-----------|
| **IDE discoverability** | Registry lookups are less navigable than class methods. Mitigate with type annotations. |
| **Python vs TypeScript** | Pi-mono's discriminated unions map well to TS. Python uses `@dataclass` + `Literal` which works but is less ergonomic. |
| **Provider count scaling** | Registry pattern pays off more with more providers. With only Claude + Gemini as primaries, it's more abstraction than strictly needed. But we have 8+ providers already. |
| **SDK coupling** | Claude Agent SDK owns the agentic loop. The registry adapter wraps output but doesn't reimplement the loop. This is correct — let the SDK do its job. |

## Phased Implementation Plan

### Phase 1: Unified StreamEvent + Single Tool Processor (1-2 days)
- Expand `StreamEvent` with `toolcall_start/delta/end` types
- Merge `tool_claude_processor.py` + `tool_gemini_processor.py` into one generic processor
- Kill the `if provider == "claude"` branching in `tool_router.py`
- **Result**: All tool event storage goes through one path

### Phase 2: Extract Shared Modules (2-3 days)
- Extract `CloudCodeClient` into shared module (kills Gemini ↔ CloudCode Claude duplication)
- Create unified `convert_messages()` base with per-provider overrides (kills 4x message conversion)
- Fix Gemini module-level mutable state
- **Result**: 4x → 1x message conversion, 2x → 1x CloudCode

### Phase 3: Provider Registry (1 week)
- Implement `registry.py` with `register()` / `get()`
- Convert each adapter from class → module with functions
- Replace `_ADAPTER_FACTORIES` dict and `get_adapter()` with registry
- Replace `ProviderChainManager` to use registry
- **Result**: Full architectural shift, no more class hierarchy

### Phase 4: Cross-Provider Message Transformation (2-3 days)
- Implement `transform_messages()` inspired by pi-mono
- Handle thinking block normalization, tool ID mapping, orphaned tool calls
- Enable model switching mid-conversation
- **Result**: New capability, production-quality message replay

### Phase 5: Cleanup + Tests (2-3 days)
- Delete dead adapter files
- Write provider × method test matrix
- Update imports throughout codebase
- **Result**: Clean codebase, confidence in correctness

---

## Files to Read Before Starting

### Pi-mono Reference (key patterns)
- `/home/kasadis/references/pi-mono/packages/ai/src/api-registry.ts` — registry mechanics
- `/home/kasadis/references/pi-mono/packages/ai/src/types.ts` — unified types
- `/home/kasadis/references/pi-mono/packages/ai/src/stream.ts` — public streaming API
- `/home/kasadis/references/pi-mono/packages/ai/src/providers/anthropic.ts` — full provider impl
- `/home/kasadis/references/pi-mono/packages/ai/src/providers/transform-messages.ts` — cross-provider transform
- `/home/kasadis/references/pi-mono/packages/ai/src/utils/event-stream.ts` — async event stream

### Current Codebase (what gets replaced)
- `/home/kasadis/agent-hub/backend/app/adapters/base.py` — current ABC
- `/home/kasadis/agent-hub/backend/app/adapters/types.py` — current types
- `/home/kasadis/agent-hub/backend/app/adapters/claude.py` — dual-mode adapter
- `/home/kasadis/agent-hub/backend/app/adapters/gemini.py` — dual-mode adapter
- `/home/kasadis/agent-hub/backend/app/adapters/openai_compat.py` — good pattern to preserve
- `/home/kasadis/agent-hub/backend/app/api/complete/tool_router.py` — hard-coded routing
- `/home/kasadis/agent-hub/backend/app/api/complete/tool_claude_processor.py` — Claude event processor
- `/home/kasadis/agent-hub/backend/app/api/complete/tool_gemini_processor.py` — Gemini event processor
- `/home/kasadis/agent-hub/backend/app/api/complete/tool_handler_utils.py` — per-provider tool loops
- `/home/kasadis/agent-hub/backend/app/adapters/helpers_adapters.py` — factory dict

### Related (affected by changes)
- `/home/kasadis/agent-hub/backend/app/api/complete/tool_handlers.py` — calls tool loops
- `/home/kasadis/agent-hub/backend/app/api/complete/_core_helpers.py` — calls route_tool_execution
- `/home/kasadis/agent-hub/backend/app/services/provider_chain.py` — fallback chain
- `/home/kasadis/agent-hub/backend/app/services/agent_routing.py` — model → provider resolution
