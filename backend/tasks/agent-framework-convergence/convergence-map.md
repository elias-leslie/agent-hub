# Convergence Map — agent-hub → pi-mono

**Phase 0.5 deliverable.** Synthesis derived from `pi-mono-catalog.md`, `agent-hub-current.md`, `downstream-consumers.md`.

> **STATUS — OPERATOR-APPROVED, AUTONOMOUS EXECUTION.** The task description's "0.6 Pause and review" gate and any other "operator review required" / "do not start until operator approval" language in the task description are **SUPERSEDED**. The operator has reviewed Phase 0, approved the classifications in Parts A–C, and locked decisions for D1–D10 (see **Part D: Decisions** below). **Phase 1+ proceeds autonomously without further pausing.** The main goal — "closely follow the shape of pi-mono" — is the single optimization criterion. Where this document is ambiguous, defer to pi-mono.

---

## Part A — pi-mono → agent-hub primitive mapping

For every pi-mono primitive, the agent-hub equivalent (if any) and the convergence verdict.

### A1. Universal interface

| pi-mono primitive (file:line) | agent-hub equivalent | Verdict |
|-------------------------------|----------------------|---------|
| `ApiProvider` interface — 2 methods: `stream`, `streamSimple` (api-registry.ts:23) | `ProviderAdapter` ABC — 5 methods: `complete`, `stream`, `health_check`, `start_tool_session` + property `provider_name` (`adapters/base.py`) plus 2 implicit `getattr`-checked methods (`complete_with_tool_events`, `complete_with_tools`) | **REPLACE.** Collapse to one method `async def stream(model, context, options) -> AsyncIterator[AssistantMessageEvent]`. Drop `complete` (becomes `stream().result()`), drop `complete_with_tool_events`/`complete_with_tools` (caller's tool loop drives multi-turn). Drop `start_tool_session` + `ProviderRuntimeSession`. Keep `health_check` only if downstream API needs it (verify; otherwise remove). |
| `registerApiProvider(provider, sourceId?)` + `getApiProvider(api)` registry (api-registry.ts:30+) | `AdapterRegistry` (`adapters/registry.py:401L`) with lazy imports + caching | **REPLACE.** Port pi-mono's lightweight registry. Keyed by `api` string (e.g. `"anthropic-messages"`, `"openai-completions"`). Lazy-load each provider module the way `providers/register-builtins.ts` does. agent-hub registry has accumulated capability-aware routing logic that does NOT belong here — that moves to a separate `routing/` layer (see B5). |

### A2. Universal types

| pi-mono primitive | agent-hub equivalent | Verdict |
|-------------------|----------------------|---------|
| `Message = UserMessage \| AssistantMessage \| ToolResultMessage` (types.ts) — discriminated union | `adapters/types.py:Message` — single dataclass with `role: Literal["user","assistant","system"]` and `content: str \| list[dict]` | **REPLACE.** Port pi-mono's discriminated union. Drop `"system"` role (pi-mono puts system prompt on `Context.systemPrompt`). |
| `AssistantMessage` with `content: (TextContent\|ThinkingContent\|ToolCall)[]`, `usage`, `stopReason`, `diagnostics?`, `responseId?`, `responseModel?` | (split across `CompletionResult` × 4 definitions; tool calls in `ToolCallResult`; thinking in `thinking_content`/`thinking_tokens` flat fields on CompletionResult) | **REPLACE.** Becomes the one universal carrier. Eliminates the 4 `CompletionResult` definitions. |
| `ToolResultMessage{ toolCallId, toolName, content, isError, details? }` | tool result messages embedded as dicts in `Message.content` (no type) | **REPLACE.** Port verbatim. |
| `TextContent`, `ThinkingContent`, `ImageContent`, `ToolCall` content blocks | (no canonical content blocks — providers translate ad-hoc) | **REPLACE.** Port verbatim. |
| `Usage{ input, output, cacheRead, cacheWrite, totalTokens, cost }` | `CompletionResult` flat fields `input_tokens, output_tokens` + `CacheMetrics{ cache_creation_input_tokens, cache_read_input_tokens }` | **REPLACE.** Port `Usage` with cost dict (currently agent-hub computes cost in caller code; consolidate). |
| `StopReason = "stop"\|"length"\|"toolUse"\|"error"\|"aborted"` | `finish_reason: str \| None` — free-form strings | **REPLACE.** Port the constrained enum. **NOTE for D2 — finish_reason values consumers may switch on.** |
| `Tool{ name, description, parameters: TSchema }` | `ToolDefinition` (in `api/complete/request_schemas.py`) — different shape | **KEEP-AND-COLLAPSE.** Port pi-mono shape internally; map at the HTTP boundary if downstream consumers send the current `ToolDefinition` shape. |
| `StreamOptions{ temperature, maxTokens, signal: AbortSignal, apiKey?, transport?, cacheRetention?, sessionId?, onPayload?, onResponse?, headers?, timeoutMs?, maxRetries?, maxRetryDelayMs?, metadata? }` | scattered kwargs on `complete()`/`stream()`; cancellation via async `StreamContext` static methods | **REPLACE.** Port `StreamOptions` and use `asyncio.CancelledError`-via-signal pattern. |
| `SimpleStreamOptions extends StreamOptions { reasoning?, thinkingBudgets? }` | `thinking_level` on request schema, plus per-provider thinking config (`thinking.py`, `claude_settings.py`, `gemini_thinking.py`) | **REPLACE.** Port `SimpleStreamOptions`. |
| `Model<TApi>{ id, name, api, provider, baseUrl, reasoning, thinkingLevelMap?, input, cost, contextWindow, maxTokens, headers?, compat? }` | `backend/app/constants/catalog_entries.py` (out of scope per task) + scattered provider config | **OUT OF SCOPE.** Per task NOT-IN-SCOPE: "Model registry/catalog (backend/app/constants/catalog_entries.py is fine)". Map catalog → `Model<TApi>` at the boundary. |
| `Context{ systemPrompt?, messages, tools? }` | request_schemas.py mixes context into `CompletionRequest` | **REPLACE** the internal carrier. HTTP `CompletionRequest` stays the boundary. |
| `AssistantMessageEvent` — 12-variant discriminated union (start, text/thinking/toolcall × start/delta/end, done, error) | `StreamEvent` (8 variants, flat dataclass) + `ToolEvent` (defined in `gemini_events.py`!) + DB persistence of session events | **REPLACE.** Port the 12-variant union. Eliminates `ToolEvent` entirely. SSE wire events at the HTTP boundary keep their current names (Section 6 of downstream-consumers.md) — they're a separate concern from the internal event stream. |

### A3. Stream utilities

| pi-mono primitive | agent-hub equivalent | Verdict |
|-------------------|----------------------|---------|
| `stream(model, context, options)`, `complete(model, context, options)`, `streamSimple`, `completeSimple` (stream.ts) | scattered — adapters have direct entry methods | **REPLACE.** Port the 4 thin wrappers. `complete()` is `stream().result()` — no separate non-streaming code. |
| `EventStream<T,R>` + `AssistantMessageEventStream` (utils/event-stream.ts) | (no canonical equivalent) | **REPLACE.** Port both classes. Used internally by every provider. |
| `getEnvApiKey(provider)` (env-api-keys.ts) | scattered per-provider env var lookups | **REPLACE.** Port the central function. |

### A4. Provider files

| pi-mono provider | agent-hub equivalent | Verdict |
|------------------|----------------------|---------|
| `providers/anthropic.ts` (1207L) + `utils/oauth/anthropic.ts` (402L) | `claude.py` + 17 other `claude_*`/`_claude_*` files (18 total, ~3362L) + `codex_oauth.py` + `codex_auth.py` + `codex_sse.py` + `codex_token_cache.py` (3 more files, ~1300L) | **REPLACE.** Collapse into ONE `backend/app/llm/providers/anthropic.py` (with shared `utils/oauth/anthropic.py` if pi-mono's split is followed). The Codex tree is a PARALLEL duplicate of the same OAuth Claude SDK; converges into the same single anthropic provider. |
| `providers/openai-completions.ts` (1148L) | `openai_compat.py` + `_openai_compat_helpers.py` + `openai.py` + `xai.py` + `openrouter.py` + `kimi_code.py` + 6 stubs + `openai_tool_events.py` + `_openai_tool_loop.py` (~13 files, ~1660L) | **REPLACE.** Collapse into ONE `backend/app/llm/providers/openai_completions.py`. xAI/OpenRouter/Kimi/Moonshot/DeepSeek/Zhipu/Nvidia/Minimax/Cerebras/etc. are all consumers of this single provider — they're a **catalog** entry (`provider` field, `baseUrl`, `compat?`), not separate providers. |
| `providers/openai-responses.ts` (295L) + `providers/openai-responses-shared.ts` (551L) + `providers/azure-openai-responses.ts` (281L) + `providers/openai-codex-responses.ts` (1351L) | (no equivalent) | **NEW-PORT.** Bring these in if/when needed. Today agent-hub does not use the OpenAI Responses API — skip for v1; revisit when there's a model requiring it. |
| `providers/google.ts` (501L) + `providers/google-vertex.ts` (568L) + `providers/google-shared.ts` (350L) | 13 `gemini_*` files (~1678L) | **REPLACE.** Collapse to `backend/app/llm/providers/google.py` + (optional) `google_vertex.py` + `google_shared.py`. |
| `providers/amazon-bedrock.ts` (956L) | (no equivalent in agent-hub) | **NEW-PORT.** Bring in if/when a model needs it (Claude via Bedrock, etc.) — skip for v1 unless catalog requires. |
| `providers/mistral.ts` (634L) | (no equivalent) | **NEW-PORT.** Skip for v1. |
| `providers/cloudflare.ts` (35L — URL helper only) | `cloudflare.py` (92L — full Cloudflare Workers AI adapter) | **DIVERGENCE — JUSTIFY.** Agent-hub treats Cloudflare Workers as a first-class provider (not just a gateway). Either: (a) collapse to a `Model.baseUrl` routing in `openai_completions.py` if Cloudflare Workers expose OpenAI-compat surface; (b) keep `cloudflare.py` as its own provider file (single-file shape) — justified divergence because agent-hub has product-level features that depend on Workers (verify with operator). |
| `providers/faux.ts` (499L) | scattered test fixtures | **NEW-PORT.** Add a faux provider for tests. Eliminates ad-hoc per-test mocking. |
| `providers/transform-messages.ts` (220L) | per-provider conversion + `adapters/utils.py:ToolCallIdNormalizer` + scattered helpers | **REPLACE.** Port verbatim as shared helper. |
| `providers/simple-options.ts` (50L) | `thinking.py` (77L) + per-provider thinking config | **REPLACE.** Port as the central reasoning-level mapper. |
| `providers/github-copilot-headers.ts` (37L) | (no equivalent) | **NEW-PORT** if a model needs it; skip otherwise. |

### A5. OAuth

| pi-mono primitive | agent-hub equivalent | Verdict |
|-------------------|----------------------|---------|
| `utils/oauth/` — 7 files / 1622L (anthropic, github-copilot, openai-codex, index, types, pkce, oauth-page) | `claude_auth.py` (196L) + `claude_oauth.py` (171L) + `codex_auth.py` (289L) + `codex_token_cache.py` (72L) + scattered token storage | **REPLACE.** Adopt pi-mono's structure: per-provider OAuth file + shared `index.py` registry + `pkce.py` + `types.py`. The two parallel Anthropic OAuth paths (Claude CLI vs. Codex SDK) collapse to one. |

### A6. Models / env / utilities

| pi-mono primitive | agent-hub equivalent | Verdict |
|-------------------|----------------------|---------|
| `models.ts` + `models.generated.ts` (17,344L total — generated registry) | `backend/app/constants/catalog_entries.py` | **OUT OF SCOPE** per task. Keep agent-hub's catalog. Provide `Model<TApi>` view at the adapter boundary. |
| `env-api-keys.ts` (210L) | scattered per-provider env lookups | **REPLACE.** Port as `backend/app/llm/env_api_keys.py`. |
| `utils/validation.ts` (324L) — TypeBox schema validation | `backend/app/services/tools/` (validation scattered) | **REPLACE.** Port; use `pydantic`/`jsonschema` instead of TypeBox where needed. |
| `utils/overflow.ts` (156L) — context overflow detection patterns | scattered error-classification logic | **NEW-PORT.** Adopt; consolidates 30+ provider error patterns. |
| `utils/json-parse.ts` (124L) — streaming JSON repair | per-adapter JSON parsing | **REPLACE.** Port. |
| `utils/event-stream.ts` (87L) | (no canonical equivalent) | **REPLACE.** Port verbatim. |
| `utils/diagnostics.ts` (45L) | scattered error handling | **NEW-PORT.** Adopt. |
| `utils/headers.ts`, `hash.ts`, `sanitize-unicode.ts`, `typebox-helpers.ts` | tiny helpers, mostly absent | **NEW-PORT.** Adopt as needed. |

---

## Part B — agent-hub → KEEP / REMOVE / REPLACE / NEW classification

Every agent-hub primitive in `backend/app/adapters/` and `backend/app/api/complete/`, classified.

**Verdict legend:**
- **KEEP-AND-COLLAPSE**: agent-hub feature is needed; it stays but is consolidated (fewer files, single canonical type).
- **REMOVE-THEATRE**: no clear job, no pi-mono analogue, deletes outright.
- **REPLACE-WITH-PIMONO**: pi-mono has a direct equivalent; port pi-mono's version, delete agent-hub's.
- **NEW-REQUIREMENT-NOT-IN-PIMONO**: legitimate feature agent-hub has that pi-mono doesn't; **must be justified in Part C** with the constraint that it can't be expressed in pi-mono's vocabulary.

### B1. `backend/app/adapters/` — core/types

| agent-hub primitive | Verdict | Notes |
|---------------------|---------|-------|
| `base.py:ProviderAdapter` (5-method ABC) | REPLACE-WITH-PIMONO | Becomes pi-mono `ApiProvider` (one `stream` method). |
| `types.py:CompletionResult` | REPLACE-WITH-PIMONO | Becomes `AssistantMessage`. |
| `types.py:StreamEvent` | REPLACE-WITH-PIMONO | Becomes `AssistantMessageEvent` (12-variant discriminated union). |
| `types.py:Message` | REPLACE-WITH-PIMONO | Becomes pi-mono `Message = UserMessage \| AssistantMessage \| ToolResultMessage`. |
| `types.py:CacheMetrics` | REPLACE-WITH-PIMONO | Folded into pi-mono `Usage`. |
| `types.py:ToolCallResult` | REPLACE-WITH-PIMONO | Becomes pi-mono `ToolCall` (content block). |
| `types.py:ContainerState` | KEEP-AND-COLLAPSE | Container support is an agent-hub feature (sandboxed tool execution). Carry on `AssistantMessage` as an optional field, or on a `ToolResultMessage.details`. See D5. |
| `runtime_session.py:ProviderRuntimeSession` | REMOVE-THEATRE | Pi-mono's stream IS the session; cancellation via `AbortSignal`. Each provider yields events directly — no need for a separate session class. |
| `runtime_session.py:StreamBackedRuntimeSession` | REMOVE-THEATRE | Wraps an iterator with interrupt/close — pi-mono uses native asyncio cancellation. |
| `registry.py` (capability-aware routing + lazy imports) | REPLACE-WITH-PIMONO **for lazy imports**; the capability-routing logic is **NEW-REQUIREMENT** (Part C — but moves out of `llm/` into `routing/`) |
| `errors.py` + `_errors_types.py` + `_errors_retry_delay.py` (273L) | KEEP-AND-COLLAPSE | Port the error types; consolidate into one file. Retry-delay calc maps onto pi-mono `StreamOptions.maxRetries`/`maxRetryDelayMs`. |
| `event_stream.py:StreamFromComplete` (158L) — complete()→stream() bridge | REMOVE-THEATRE | Only needed because some providers have non-streaming `complete()` paths. With pi-mono shape (every provider native streaming), this entire file disappears. |
| `tool_result_payload.py:ToolResultPayload` (24L) | REMOVE-THEATRE | Wrapper-only type; folds into `ToolResultMessage`. |
| `thinking.py` (77L) | REPLACE-WITH-PIMONO | Becomes `simple-options.ts` port. |
| `utils.py:ToolCallIdNormalizer` (87L) | REPLACE-WITH-PIMONO | Becomes `transform-messages.py:normalize_tool_call_id` callback. |

### B2. `backend/app/adapters/` — provider files

| Provider file group | Verdict | Notes |
|---------------------|---------|-------|
| 18 `claude_*`/`_claude_*` files (~3362L) | REPLACE-WITH-PIMONO | Collapse to ONE `backend/app/llm/providers/anthropic.py` (with shared `utils/oauth/anthropic.py`). |
| 3 `codex_*` files (~1300L) | REMOVE-THEATRE (collapse into anthropic provider) | Codex IS Anthropic OAuth — there is no separate `Codex` provider. The duplication is pure theatre. |
| 13 `gemini_*` files (~1678L) | REPLACE-WITH-PIMONO | Collapse to `google.py` + optional `google_vertex.py` + shared `google_shared.py`. |
| `openai_compat.py` + `_openai_compat_helpers.py` + `openai.py` + `xai.py` + `openrouter.py` + `kimi_code.py` + 6 stubs + `openai_tool_events.py` + `_openai_tool_loop.py` (~13 files, ~1660L) | REPLACE-WITH-PIMONO | Collapse to ONE `openai_completions.py`. xAI/OpenRouter/Kimi/Moonshot/DeepSeek/Zhipu/Nvidia/Minimax become **catalog entries**, not separate providers. |
| `cloudflare.py` (92L — text adapter) | **JUSTIFY** (see A4) | Decide: collapse into openai_completions (if Workers AI is OpenAI-compatible at the wire level) OR keep as its own provider. Single-file regardless. |
| 4 image adapters (`gemini_image`, `cloudflare_image`, `nvidia_image`, `minimax_image`, `image_base`) | OUT OF SCOPE per task | Untouched. |

### B3. `backend/app/api/complete/` — tool loops

| File group | Verdict | Notes |
|------------|---------|-------|
| `tool_handlers.py` (205L) + `tool_handler_utils.py` (301L) + `multi_turn_executor.py` (139L) + `multi_turn_loop.py` (172L) + `multi_turn_helpers.py` (238L) — **sync tool loop, 5 files / ~1055L** | REMOVE-THEATRE **down to ONE file** | Pi-mono doesn't have tool loops in the adapter; they're caller-side. Agent-hub is a SERVICE and must run the loop server-side because the HTTP API contract has `execute_tools=True`. But ONE tool-loop file is enough. Target: `backend/app/llm/tool_loop.py` (~200L). |
| `streaming_tool_loop.py` (156L) + `streaming_tool_executor.py` (171L) + `streaming_tool_messages.py` (102L) + `streaming_runtime_session.py` (415L) — **streaming tool loop, 4 files / ~844L** | REMOVE-THEATRE **— merge into the single tool loop above** | The streaming vs sync split disappears once every provider is native streaming (because `complete()` is `stream().result()` — see A3). One tool loop, one pipeline. |
| `streaming.py` (205L) + `streaming_handlers.py` (313L) + `streaming_context.py` (135L) + `streaming_persistence.py` (411L) — **streaming infra, 4 files / ~1064L** | KEEP-AND-COLLAPSE | The SSE wire format (`content/thinking/tool_use/tool_result/done/error` events with `seq`) is a DOWNSTREAM CONTRACT — preserved. But the implementation collapses into one file that adapts `AssistantMessageEvent` → SSE wire events. Target: `backend/app/api/complete/sse_writer.py` (~250L). `StreamContext` thread-local hack disappears; context is passed explicitly. |
| `_ExecutionState` (in `tool_handler_utils.py`) | REMOVE-THEATRE | The state belongs INSIDE the tool loop function as locals, not as a shared 13-field mutable dataclass. |
| `ToolExecutionResult` (in `tool_models.py`) | REMOVE-THEATRE | Identical to `CompletionInternalResult + 1 field`. Folds into pi-mono `AssistantMessage`. |
| `closeout_policy.py` (259L) | KEEP-AND-COLLAPSE (mostly REMOVE) | Most heuristics are workarounds for buggy provider streams. With pi-mono shape, simplifies to a small `finalize_turn` helper. Target: ~50–100L. |

### B4. `backend/app/api/complete/` — sessions

| File group | Verdict | Notes |
|------------|---------|-------|
| `session_manager.py` (198L) + `_session_helpers.py` (162L) + `session_setup.py` (110L) — **3 files / ~470L** | NEW-REQUIREMENT (see C1) — but COLLAPSE to ONE file. Target: `backend/app/api/complete/session_repo.py` (~200L). |
| `runtime_session_registry.py` (43L) | REMOVE-THEATRE | Tied to the `ProviderRuntimeSession` abstraction, which goes away. |
| `agent_loop.py` (243L) | KEEP-AND-COLLAPSE | Multi-agent loop is the orchestration layer above the unified tool loop. Survives but as a thin caller of `tool_loop.run()`. |

### B5. `backend/app/api/complete/` — request/response/orchestration

| File group | Verdict | Notes |
|------------|---------|-------|
| `endpoints.py` (69L) + `async_endpoints.py` (133L) + `estimate_endpoint.py` (36L) | KEEP | HTTP entrypoints; routes are immutable per downstream contract. |
| `request_schemas.py` (349L) + `response_schemas.py` (166L) + `schemas.py` (60L) + `usage_schemas.py` (76L) + `validation.py` (80L) | KEEP-AND-COLLAPSE | Wire-format Pydantic models stay. Internal `CompletionInternalResult` (types.py) is REPLACED by `AssistantMessage` + a thin response builder. |
| `complete_orchestrator.py` (188L) + `complete_execution.py` (221L) | KEEP-AND-COLLAPSE | Top-level dispatch; collapses into one file (`orchestrator.py`, ~200L) once non-streaming path is `stream().result()`. |
| `resolution.py` (383L) — model/provider routing | NEW-REQUIREMENT (see C2). Move to `backend/app/routing/`. |
| `request_setup.py` (350L) + `result_builder.py` (104L) + `result_finalizer.py` (135L) | KEEP-AND-COLLAPSE | Boundary helpers (HTTP request → internal Context, internal AssistantMessage → HTTP response). Collapse to one file each side: `request_translator.py` + `response_builder.py`. |

### B6. `backend/app/api/complete/` — advanced features (mostly NEW-REQUIREMENT)

| File group | Verdict | Notes |
|------------|---------|-------|
| `cache_handler.py` (110L) — prompt cache | KEEP-AND-COLLAPSE | Maps to pi-mono `StreamOptions.cacheRetention`. Mostly thin shim once boundaries align. |
| `context_compaction.py` (184L) | NEW-REQUIREMENT (see C3) |
| `citation_tracker.py` (199L) + `_citation_helpers.py` (222L) | NEW-REQUIREMENT (see C4). Move out of `complete/` to `backend/app/memory/citations.py`. |
| `memory_handler.py` (102L) — semantic memory injection | NEW-REQUIREMENT (see C4). Move to `backend/app/memory/`. |
| `precision_search_guidance.py` (256L) | NEW-REQUIREMENT (see C5). Move to `backend/app/memory/` or `prompt_assembly/`. |
| `finish_reason_handler.py` (157L) | KEEP-AND-COLLAPSE | Maps provider finish reasons to pi-mono `StopReason`. Becomes a small per-provider helper. |
| `turn_processor.py` (157L) + `turn_processor_helpers.py` (69L) + `turn_budget.py` (41L) | KEEP-AND-COLLAPSE | Folds into the unified `tool_loop.py`. |
| `tool_event_processor.py` (297L) + `tool_event_storage.py` (152L) | NEW-REQUIREMENT (see C6 — session event storage). Move to `backend/app/sessions/event_storage.py`. |
| `tool_models.py:AgentProgress` (53L) | KEEP-AND-COLLAPSE | One progress type; merge with `orchestration_models.py:AgentProgressInfo`. |
| `tool_progress.py:ProgressTracker` (115L) | KEEP | Drives `progress_log` in HTTP response. |
| `tool_provisioner.py` (187L) + `tool_router.py` (93L) + `tool_response_finalizer.py` (221L) + `tool_result_builder.py` (146L) | KEEP-AND-COLLAPSE | Tool provisioning + routing + result handling — service feature, but consolidate (~400L target). |
| `error_summary.py` (71L) + `error_handlers.py` (211L) | KEEP-AND-COLLAPSE | Maps internal errors → HTTP `error_summary`. Folds together. |
| `execution_observability.py` (138L) | NEW-REQUIREMENT (see C7) |

### B7. `backend/app/api/complete/` — helper sprawl

| File group | Verdict | Notes |
|------------|---------|-------|
| `handlers.py` (118L) + `handler_helpers.py` (292L) + `event_helpers.py` (105L) + `helpers.py` (151L) + `_core_helpers.py` (128L) + `orchestration_helpers.py` (226L) + `async_dispatch.py` (203L) + `execution.py` (294L) + `core.py` (193L) + `work_context.py` (80L) — **~1790L** | REMOVE-THEATRE (mostly) | The "_X_helpers.py / X_helpers.py" 2024 stylistic pattern. Most of these are micro-extractions whose contents fold back into their callers under pi-mono shape. Target: delete in Phase 4 after the new structure stabilizes; carry residue forward into the unified orchestrator + tool_loop. |

---

## Part C — NEW-REQUIREMENT bucket (justifications)

Each item below must demonstrate why it **cannot** be expressed in pi-mono's vocabulary. If it can, it belongs in B (KEEP/REMOVE/REPLACE), not here.

### C1. Database-backed session persistence
**What:** `Session` row in Postgres holding conversation history; `parent_session_id`, `fork`, `promote`, `external_id`.
**Why not in pi-mono:** pi-mono is a library — caller passes `messages: Message[]` per call and stores history wherever they like. agent-hub is a **service**: every downstream consumer (SummitFlow, portfolio-ai, vantage) passes a `session_id` and expects agent-hub to load history server-side. Removing this breaks every consumer.
**Where it lives in the refactor:** `backend/app/api/complete/session_repo.py` (consolidated from 3 files → 1) + existing `backend/app/db/models/sessions.py` (untouched).
**Convergence rule:** the **adapter layer (`backend/app/llm/`)** does NOT touch sessions. Adapters take `Context{ systemPrompt?, messages, tools? }` like pi-mono. The session boundary translates DB rows ↔ `Context` at the HTTP/orchestrator boundary only.

### C2. Cross-provider routing + fallback
**What:** Auto-routing across providers (adaptive routing, manual routes, workload profiles, cost preferences, fallback chains, canary percentages).
**Why not in pi-mono:** pi-mono callers pick the model and call `stream(model, ...)`. agent-hub's service value-proposition is "give me an agent slug + work context, I'll pick the best model and fall back across providers". Removing this breaks vantage, SummitFlow, portfolio-ai.
**Where it lives in the refactor:** new `backend/app/routing/` package. Inputs: `agent_slug`, `workload_profile`, `task_type`, `cost_preference`, `routing_exclude_providers`. Output: ordered list of `Model<TApi>` to try. The `backend/app/llm/` layer is consumed BY the router, not the other way around.
**Convergence rule:** routing decisions are produced OUTSIDE the adapter. Adapters never know about fallback. Failed adapters surface as `AssistantMessage{ stopReason: "error" }`; the router catches and tries the next model.

### C3. Context-window compaction
**What:** Summarize/drop older messages when context window is approaching limit, before the next provider call.
**Why not in pi-mono:** pi-mono ships `session-resources.ts` (24L) as a minor compaction helper but largely treats compaction as a caller concern. Since agent-hub maintains conversation history server-side (C1), the compactor lives server-side too.
**Where it lives:** `backend/app/sessions/compaction.py`. Runs at the orchestrator level, before the adapter is invoked. The adapter just sees `Context{ messages: [compacted set] }`.
**Convergence rule:** compaction never lives inside the adapter layer.

### C4. Memory injection + citation tracking
**What:** Inject semantic-memory facts into the system prompt before calling the adapter; track which memory UUIDs were "cited" (referenced) by the assistant in the response.
**Why not in pi-mono:** pi-mono has no concept of memory — caller assembles the system prompt and messages and calls. agent-hub provides memory as a **product feature** to every downstream consumer; portfolio-ai and SummitFlow both rely on `memory_facts_injected, memory_uuids, cited_uuids` in responses for attribution.
**Where it lives:** `backend/app/memory/` (already exists). Memory prompt assembly happens before adapter invocation; citation extraction happens after the assistant message is final. Adapter is unaware of memory.
**Convergence rule:** the **adapter doesn't know what memory is.** It takes a `Context.systemPrompt` and `Context.messages`. Memory layer assembles the prompt; citation layer post-processes the result.

### C5. Tool catalog + tool execution server-side
**What:** When `execute_tools=True`, agent-hub runs the tool loop server-side (Bash, Read, Write, Edit, Grep, browser tools, MCP tools, etc.) without round-tripping to the caller.
**Why not in pi-mono:** pi-mono emits `ToolCall`s and expects the caller to execute them. agent-hub provides a hosted tool runtime — this IS the product. Removing it removes the reason SummitFlow/vantage call agent-hub at all.
**Where it lives:** `backend/app/llm/tool_loop.py` (consolidated tool loop, ~200L) + `backend/app/services/tools/` (existing tool implementations, unchanged). The tool loop is a CALLER of the adapter — it lives ABOVE `backend/app/llm/`, not inside.
**Convergence rule:** the unified tool loop is the canonical consumer of `AssistantMessageEvent`. Providers never know there's a tool loop.

### C6. Session event storage + WebSocket observability
**What:** Record every assistant event (text, thinking, tool_use, tool_result) into a `session_events` table, queryable via `GET /api/sessions/{id}/events` and subscribable via `WS /api/events`.
**Why not in pi-mono:** pi-mono streams events into the void — the caller may consume them, but pi-mono itself doesn't persist them. agent-hub treats events as a first-class audit trail.
**Where it lives:** `backend/app/sessions/event_storage.py` (consolidates `tool_event_processor.py` + `tool_event_storage.py`). Hooks the `AssistantMessageEvent` stream coming out of the tool loop; persists to DB; publishes to Redis/WS bus.
**Convergence rule:** event storage is downstream of the adapter — it consumes the same stream the SSE writer does. Both are siblings, not nested.

### C7. Async task dispatch (Hatchet/queue)
**What:** `async_execution=True` on `POST /api/complete` returns 202 immediately; work runs in a Hatchet worker; `GET /api/complete/tasks/{task_id}` polls status.
**Why not in pi-mono:** pi-mono is synchronous (returns a stream you await). agent-hub provides async dispatch for long-running agentic work (autocode, autonomous mode). vantage's entire integration is async-dispatch-based.
**Where it lives:** `backend/app/workflows/completion.py` (existing Hatchet workflow). The async worker just calls the same in-process orchestrator that the synchronous path does.
**Convergence rule:** async dispatch is a transport detail above the adapter; the adapter is the same in both cases.

### C8. Per-agent registry (agents as data)
**What:** `Agent` rows in Postgres with `slug`, `system_prompt`, `primary_model_id`, `fallback_models`, `tools`, `memory_config`, `routing`, etc. `/api/agents` CRUD endpoints.
**Why not in pi-mono:** pi-mono treats `Model<TApi>` as the configuration unit. agent-hub adds a layer above: an `Agent` is a configured set (prompt + model + memory + tools) referred to by slug. Every downstream consumer uses agent slugs.
**Where it lives:** `backend/app/api/agents.py` + DB models (unchanged). Agent slug → resolved `Context` happens at the orchestrator boundary; the adapter never sees a slug.
**Convergence rule:** the adapter doesn't know what an agent is.

### C9. Cost tracking / billing
**What:** Per-request cost ledger; daily/hourly budgets per agent; analytics endpoints.
**Why not in pi-mono:** pi-mono computes cost into `Usage.cost` but doesn't persist it. agent-hub persists for billing/analytics.
**Where it lives:** `backend/app/services/cost_tracking.py` (existing, untouched). Hooks the final `AssistantMessage.usage`.
**Convergence rule:** the adapter emits `Usage`; cost persistence is a downstream consumer of it.

### C10. Container / sandbox execution
**What:** `ContainerState` (`id`, `expires_at`) on completions. Tool execution can run in a sandboxed container.
**Why not in pi-mono:** pi-mono knows nothing of containers.
**Where it lives:** TBD — currently scattered in tool_loop concerns. **OPEN QUESTION D5.**
**Convergence rule (proposed):** carry as `AssistantMessage.metadata?.container?` or `ToolResultMessage.details.container?`. The adapter doesn't manage containers; the tool runtime does.

---

## Part D — Decisions (locked, autonomous execution)

The classifications above embed assumptions. All ten decisions below are **locked**. Future sessions follow these without re-litigating.

### D1. New namespace name — **`backend/app/llm/`**
Per task description. Top-level layout:
```
backend/app/llm/
├── __init__.py
├── types.py              # universal types (Message, AssistantMessage, AssistantMessageEvent, Usage, StopReason, Tool, Context, StreamOptions, SimpleStreamOptions, Model)
├── event_stream.py       # EventStream<T,R>, AssistantMessageEventStream
├── transform_messages.py # universal Message normalizer
├── simple_options.py     # reasoning-level mapping
├── api_registry.py       # ApiProvider interface + registry
├── stream.py             # top-level stream/complete/streamSimple/completeSimple
├── env_api_keys.py
├── tool_loop.py          # unified tool loop (replaces sync + streaming tool-loop files)
├── health.py             # health_check() (kept out of ApiProvider — see D3)
├── providers/
│   ├── __init__.py
│   ├── anthropic.py      # Phase 1.5 reference port
│   ├── openai_completions.py  # Phase 2 (collapses xAI/OpenRouter/Kimi/+stubs)
│   ├── google.py
│   ├── google_shared.py  # shared by google.py (+ google_vertex.py if added)
│   ├── cloudflare.py     # see D4
│   ├── faux.py           # test double
│   └── ...
└── utils/
    ├── __init__.py
    ├── oauth/            # mirrors pi-mono utils/oauth/
    │   ├── __init__.py
    │   ├── types.py
    │   ├── pkce.py
    │   ├── anthropic.py
    │   └── (others as needed)
    ├── diagnostics.py
    ├── overflow.py
    ├── json_parse.py
    └── validation.py
```

### D2. `finish_reason` / `StopReason` enum — **lock to pi-mono's 5 values**
Internal `StopReason: Literal["stop","length","toolUse","error","aborted"]`. Any provider-specific reason (`"max_tool_calls"`, `"timeout"`, `"context_overflow"`, etc.) maps to `"error"` or `"length"` with the human-readable detail in `AssistantMessage.errorMessage`. **Phase 1 task:** grep summitflow + portfolio-ai + vantage for `finish_reason ==` / `finish_reason !=` / `.get("finish_reason")` patterns; for any value they switch on that isn't in the enum, expose it in the SSE wire `done` event's `finish_reason` field as a string (the HTTP boundary keeps the wider vocabulary; internal types use the locked enum). HTTP wire field stays `str | None` for backward compatibility.

### D3. `health_check()` retention — **separate module, not on `ApiProvider`**
`backend/app/llm/health.py` exports `async def check_provider_health(api: str, model: Model) -> bool`. Used by `/api/orchestration/health`. The `ApiProvider` protocol has exactly two methods: `stream`, `streamSimple` (matching pi-mono).

### D4. Cloudflare provider treatment — **wire-format check in Phase 2**
Phase 2.1 task: probe Cloudflare Workers AI wire format. If it speaks OpenAI Chat Completions (it does for most LLM bindings), **collapse into `openai_completions.py`** as a `Model<"openai-completions">` entry with `baseUrl: https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` and `compat?` overrides if needed. Otherwise keep as single-file `backend/app/llm/providers/cloudflare.py`. Default: collapse (most likely). Image variants stay out of scope.

### D5. Container state carrier — **`ToolResultMessage.details.container`**
Pi-mono's `ToolResultMessage<TDetails = any>` has a generic `details?: TDetails` field exactly for this. Use `details: { container?: { id: str; expires_at: str } }`. The adapter doesn't manage containers; the tool runtime sets this field when emitting tool results. `AssistantMessage` stays container-agnostic.

### D6. `complete_with_tool_events()` and `start_tool_session()` retirement — **DELETE BOTH**
Phase 1 task: audit `ClaudeAdapter` CLI-mode tool loop for semantic differences vs. direct-API + unified tool loop. **Default verdict: theatre, delete.** Concrete check: take three real autocode tool sequences (e.g., a recent task-XXX from `git log`), replay them through (a) current Claude CLI mode and (b) direct-API + unified tool loop with same tool catalog; compare final assistant message and tool call sequence. If `(a)==(b)` modulo non-determinism, delete the CLI-mode path entirely (the entire `claude_tools_*` family of files). If `(a)!=(b)` with material gap, treat as **NEW-REQUIREMENT C11** and document. **Strong prior:** CLI mode is theatre — Anthropic's tool calling is the same wire-protocol either way. Do not let "we might want it later" justify keeping it.

### D7. Codex vs Claude — **COLLAPSE**
Same Anthropic SDK, different OAuth flow. Codex = Anthropic OAuth with the Claude Code identity system prompt. There is one Anthropic provider. The OAuth differences (Claude Pro/Max vs Claude Code) become two `OAuthProviderInterface` instances registered with different ids; both produce a bearer token consumed by the same `providers/anthropic.py`.

### D8. Architectural test — **import-linter + AST pytest**
- `import-linter` (existing dep in agent-hub's tooling — verify in Phase 5; add if missing) enforces module-level constraints: "no module outside `backend/app/llm/` imports anything in `backend/app/llm/providers/` directly; goes through `api_registry.get_api_provider()`".
- Custom AST pytest at `backend/tests/architecture/test_pimono_shape.py` enforces:
  - `ApiProvider` protocol has exactly the two declared methods `stream` and `streamSimple`
  - No class in the repo defines fields matching the `CompletionResult` shape (heuristic: 5+ overlap with the legacy 24-field set) outside `backend/app/llm/types.py:AssistantMessage`
  - No new files matching `*tool_loop*.py` / `*tool_executor*.py` / `*tool_handler*.py` outside `backend/app/llm/tool_loop.py`
  - Every file in `backend/app/llm/providers/` declares exactly one `ApiProvider` registration (catches accidental multi-provider sprawl)

### D9. Memory / citation behavior — **out-of-band**
`AssistantMessage.content` stays at pi-mono's 4 block types (`TextContent | ThinkingContent | ToolCall` + `ImageContent` in user messages). The `cited_uuids: list[str]` HTTP response field is computed post-hoc by `backend/app/memory/citation_extractor.py` from the assembled text. The adapter doesn't know about memory.

### D10. Pi-mono port style — **name-by-name match for vocabulary**
- TS `interface X` → Python: `@dataclass(slots=True)` (preferred) OR `Pydantic BaseModel` (only at HTTP boundary). NOT `typing.Protocol` unless the type is purely structural and never instantiated.
- TS discriminated union (`type T = A | B | C`) → Python `T = A | B | C` (PEP 604) where each variant is a `@dataclass` with a `type: Literal["..."]` discriminator field.
- TS `interface ApiProvider` → Python `typing.Protocol` (the one place Protocol is right — it IS purely structural).
- TS `AbortSignal` → Python `asyncio.Event` or `contextvars`-carried cancel token (pick the one already used in agent-hub; standardize in Phase 1).
- Method names: **camelCase → snake_case**, EXCEPT preserve the universal vocabulary verbatim where it appears in user-facing identifiers: `AssistantMessageEvent`, `StreamOptions`, `SimpleStreamOptions`, `Context`, `Tool`, `Usage`, `StopReason`, `Model`, `ApiProvider`. These names exist in both repos to make diffs tractable.
- File names: pi-mono's TS file names map directly to Python: `api-registry.ts` → `api_registry.py`, `transform-messages.ts` → `transform_messages.py`, `event-stream.ts` → `event_stream.py`. One exception: pi-mono's `oauth.ts` (1L re-export) collapses into `utils/oauth/__init__.py`.

---

## Part E — Recommended phase-ordering refinements

Phases 0–5 are the task's plan. Based on the audit, recommended refinements:

### E1. Phase 1 ordering — port the dependency stack bottom-up
The task lists Phase 1 as 1.1 directory → 1.2 types → 1.3 interface → 1.4 registry → 1.5 anthropic port. That's correct, but expand:

- 1.2a: `types.py` (universal types — Message family, AssistantMessage, AssistantMessageEvent, Usage, StopReason, Tool, Context, StreamOptions, SimpleStreamOptions, Model)
- 1.2b: `event_stream.py` (EventStream<T,R>, AssistantMessageEventStream)
- 1.2c: `transform_messages.py` (universal Message normalizer)
- 1.2d: `simple_options.py` (reasoning-level mapping helpers)
- 1.2e: `env_api_keys.py`
- 1.3: `api_registry.py` (ApiProvider interface + registry)
- 1.4: `stream.py` (top-level stream/complete/streamSimple/completeSimple wrappers)
- 1.5: `providers/anthropic.py` reference port (with `utils/oauth/anthropic.py` shared helper)
- 1.6: bring up the unified tool loop (`tool_loop.py`) consuming `AssistantMessageEvent` — this is when the new shape gets exercised end-to-end
- 1.7: `sse_writer.py` (adapts `AssistantMessageEvent` → SSE wire events matching downstream contract)
- 1.8: smoke test via direct call into the new pipeline; do NOT switch HTTP routes yet

### E2. Phase 2 — provider ports
Per task description, one provider per commit. Suggested order: openai_completions (→ collapses xAI + OpenRouter + Kimi + 6 stubs), google (→ replaces gemini_*), cloudflare (per D4). Bedrock + mistral + openai-responses skipped for v1 unless catalog requires.

### E3. Phase 3 — harness collapse
Once Phase 2 is green: switch the HTTP route to call the new orchestrator. The OLD `backend/app/adapters/` and `backend/app/api/complete/` files remain on disk (no imports) until Phase 4 deletion. Watch for: import-graph residue, persona/work-chat features that reach into `complete/`.

### E4. Phase 4 — deletion
After Phase 3 is green AND downstream contracts still pass: bulk-delete the old trees. Use `vulture` + manual grep. Operator approves before deletion lands.

### E5. Phase 5 — guardrails
After Phase 4 lands: architectural test (D8), ADR, memory mandate, periodic re-audit script.

### E6. Risk: SummitFlow/portfolio-ai/vantage end-to-end
Phase 4.4 requires "at least one autocode end-to-end per project". Plan: keep a "rollback HTTP route" flag that flips between OLD and NEW orchestrator until E2E confirmed on all 3 consumers. Flag removed in Phase 5.

---

## Summary table — by the numbers

| Bucket | Files affected | LOC affected |
|--------|----------------|--------------|
| **KEEP-AND-COLLAPSE** | ~25 files | ~3,500 LOC (collapses to ~12 files / ~1,800 LOC) |
| **REMOVE-THEATRE** | ~55 files | ~6,000 LOC (deleted) |
| **REPLACE-WITH-PIMONO** | ~50 files | ~10,000 LOC (replaced by ~15 files / ~5,000 LOC porting pi-mono) |
| **NEW-REQUIREMENT (justified, retained)** | ~10 files | ~2,300 LOC (collapses to ~6 files / ~1,500 LOC, moved to `routing/`, `memory/`, `sessions/`) |
| **OUT OF SCOPE (unchanged)** | 5 files | ~822 LOC (image adapters) |

**Net target:** **~38 files / ~8,300 LOC** in `backend/app/llm/` + `backend/app/api/complete/` (vs current 133 files / 21,835 LOC).

**Pi-mono reference (in-scope, hand-written):** **~42 files / ~12,624 LOC**.

The target is **smaller** than pi-mono in absolute terms because pi-mono carries 9 APIs and we'll port 3–4 for v1. The "ratio" target in the task description (within 2× of pi-mono) is comfortably met.

---

## Autonomous-execution directive

The operator has reviewed Phase 0 and approved autonomous execution through completion. **Do not pause between phases.** The single optimization criterion is **"closely follow the shape of pi-mono"** — when in doubt, re-read the relevant section of `pi-mono-catalog.md` and match it. Where pi-mono is silent (the NEW-REQUIREMENT items in Part C), follow this map's recommendations and the locked decisions in Part D. The task description's "do not write code until [audit] complete" / "operator review required" / "Pause and review" language is **superseded by this directive**: Phase 0 IS complete; proceed.

**Phase ordering reminder (from Part E):** Phase 1 (build new shape) → Phase 2 (provider ports, one per commit) → Phase 3 (harness collapse + HTTP route flip) → Phase 4 (delete old surfaces) → Phase 5 (guardrails). At the end of each PHASE (not each subtask), commit via `st commit` and optionally `st log task-e65e9ee0 "phase N complete"` so the audit trail is queryable. No subagent fan-out unless the work is independently parallelizable (provider ports in Phase 2 qualify; sequential phases do not).

**Stop conditions** (the ONLY reasons to pause and ping the operator):
1. A downstream HTTP contract genuinely needs to change (rename/remove a route, field, or SSE event type). Reference Section 10 of `downstream-consumers.md`.
2. A pi-mono primitive doesn't map AND the gap surfaces a legitimate NEW-REQUIREMENT not enumerated in Part C. Document and proceed; ping the operator only if it would alter the public HTTP contract.
3. A test suite goes red and remains red after a reasonable diagnosis pass (don't bypass with `--no-verify` or skip tests; ping the operator).

Anything else: just decide and continue.
