# CONTINUATION — task-e65e9ee0

**Read this file first. Then `pi-mono-catalog.md` and `convergence-map.md`.**

## Status (updated 2026-05-12)

- Phase 0 (audit): **COMPLETE** — commit `1518690a`.
- Phase 1 (universal shape + anthropic reference port): **COMPLETE** — commits `2c8531e2`, `c884876b`, `fc04d20d`, `4ff62952`.
- Phase 2 (provider ports): **COMPLETE** — commits `13fbe5f7` (openai_completions), `39067151` (google + google_shared), `33ad48e1` (cloudflare URL helpers; provider collapsed into openai_completions per D4), `d6c43730` (faux test double).
- Phase 3.1 (orchestrator skeleton + `LLM_USE_NEW_PIPELINE` flag): **COMPLETE** — commit `5165e9d2`. Flag default OFF.
- Phase 3.2 (session_repo collapse): **COMPLETE** — commit `530653f7`.
- Phase 3.3 (routing/ package): **COMPLETE** — commit `b4991c4b`.
- Phase 3.4 (memory move + citation_extractor): **COMPLETE** — commit `41a696aa`.
- Phase 3.5 (wire complete_internal on flag): **COMPLETE** — commit `4f80dbd9`. Flag default still OFF; baseline path covers single-turn, no-tools only.
- Phase 3.6 (tool-loop wiring + flag flip): **COMPLETE** — commits `ec117d79` (tool runner bridge + E2E test), `a868f5b2` (default → True). 3488 tests pass; pre-existing 4 failures in `tests/adapters/test_kimi_code.py`+`test_claude.py` are REMOVE-THEATRE deferred to Phase 4.
- Phase 4 cluster A (drop flag + branch + shim): **COMPLETE** — commit `f91e7643`. `llm_use_new_pipeline` flag, `is_new_pipeline_enabled` helper, `new_pipeline.py` shim, and the legacy `_CompletionCtx`/`_build_ctx`/`_run_after_session`/`_ensure_user_messages` helpers in `core.py` are gone. `complete_internal` is the single composition point. Tests moved to `tests/api/complete/test_complete_internal_unified.py`.
- Phase 4 cluster B (migrate remaining HTTP paths): **COMPLETE** — commits `40f29e8d` (`complete_internal` tolerates `db=None`; `execute_without_db` routes through it), `de1500e2` (`_try_model` in `agent_routing_completion.py` drops `adapter.complete()` in favor of `complete_internal`), `30391be3` (`stream_completion` rewritten on `orchestrator.run_completion_stream` + `sse_writer.SseWriter`; preserves all 9 SSE event types + heartbeat + cancel + persistence). 3466 tests pass.
- Phase 4 cluster D **wave 1** — delete streaming tool loop: **COMPLETE** — commit `46ed3efc`. Files removed: `streaming_tool_loop.py`, `streaming_tool_executor.py`, `streaming_tool_messages.py`, `streaming_runtime_session.py`, plus their tests. The pre-existing 4 FakeMessages failures (`tests/adapters/test_kimi_code.py`, `test_claude.py`) were removed in the same commit (REMOVE-THEATRE per Part B).
- Phase 4 cluster D **wave 2** — delete sync tool loop + theatre helpers: **COMPLETE** — commit `51ce3699`. Created `app/api/complete/progress.py` carrying `AgentProgress`. Removed 21 theatre files: `tool_handlers.py`, `tool_handler_utils.py`, `tool_models.py`, `multi_turn_executor.py`, `multi_turn_loop.py`, `multi_turn_helpers.py`, `turn_processor.py`, `turn_processor_helpers.py`, `finish_reason_handler.py`, `agent_loop.py`, `tool_router.py`, `tool_response_finalizer.py`, `tool_result_builder.py`, `tool_event_processor.py`, `tool_event_storage.py`, `tool_progress.py`, `result_builder.py`, `precision_search_guidance.py`, `_core_helpers.py`, `closeout_policy.py`, `runtime_session_registry.py` (cancel hook from `sessions.py` deleted in favor of `StreamContext.cancel` alone). Updated non-theatre consumers (`core.py`, `types.py`) to import `AgentProgress` from `.progress`. Pruned 10 theatre tests + adjusted `test_turn_budget.py`. 3389 tests pass.
- Phase 4 cluster D **wave 3** — audit live helpers and delete dead finalizer: **COMPLETE** — commit `baac3c56`. Option (b) selected: `complete_orchestrator.py` + `orchestration_helpers.py` + `handlers.py` + `handler_helpers.py` + `event_helpers.py` + `helpers.py` + `async_dispatch.py` + `execution.py` + `complete_execution.py` + `work_context.py` are still in the live HTTP chain and stay. `result_finalizer.py` was dead and deleted.
- Phase 4 cluster C step 1 — subagent migration: **COMPLETE** — commit `19a0eada`. `subagent.py`, `subagent_executor.py`, and tests now use `complete_internal(db=None)` instead of `ClaudeAdapter`/`GeminiAdapter`.
- Phase 4 cluster C (delete text `backend/app/adapters/`): **COMPLETE** — commit `21f9bae3`. Text adapter callers are gone (`context_compaction`, `CompletionService`, subagents, health/status). Legacy shared adapter dataclasses/errors moved to `app/services/llm_messages.py` and `app/services/llm_errors.py`; provider/model lookup moved to `app/routing/registry.py`; MCP constants moved to `app/services/mcp_constants.py`. Deleted legacy text adapter implementations, model-router/health-prober subsystem, and `tests/adapters/`. Image adapters and OAuth flow files remain. Changed-only gate: lint OK, types OK, architecture OK, pytest `2985 passed, 35 skipped`.
- Phase 4 cluster E (vulture sweep + dead type cleanup): **COMPLETE** — pending commit. `uvx vulture backend/app/ --min-confidence 80` is clean. Manual grep is clean for `CompletionResult`, `StreamEvent`, `ToolEvent`, `_ExecutionState`, `ToolExecutionResult`, `StreamFromComplete`, `ProviderRuntimeSession`, `RuntimeSessionRegistry`, and `AgentProgressInfo` across `backend/app`, `backend/tests`, and `backend/scripts`. `CompletionInternalResult` now wraps the pi-mono `AssistantMessage` carrier instead of declaring the legacy flat result field set; remaining HTTP callers read compatibility properties. Full no-coverage pytest: `2980 passed, 35 skipped`.
- Phase 5 (guardrails + ADR + drift audit): **NOT STARTED**. The four AST checks (a/b/c/d in convergence-map D8) will gate on the current state — (c) "no `*tool_loop*.py` / `*tool_executor*.py` / `*tool_handler*.py` outside `app/llm/tool_loop.py`" needs `app/services/tools/tool_handler.py` either renamed or carved out as an allowlist, since that file is the live tool-execution entry the new pipeline uses (per `complete_internal._make_tool_runner`).
- Phase 4 cluster D: delete REMOVE-THEATRE family in `api/complete/` (sync tool-loop 5 files, streaming tool-loop 4 files, `runtime_session_registry.py`, `tool_result_payload.py`, `handlers.py`/`handler_helpers.py`/`event_helpers.py`/`helpers.py`/`_core_helpers.py`/`orchestration_helpers.py`/`async_dispatch.py`/`execution.py`/`work_context.py`, `closeout_policy.py` slim-down).
- Phase 4 cluster E: `vulture` + manual grep on dead types (`CompletionResult` 4-way, `ToolEvent`, `_ExecutionState`, `ToolExecutionResult`, `StreamFromComplete`, `ProviderRuntimeSession`, `RuntimeSessionRegistry`, `AgentProgressInfo` merge).
- Operator approved autonomous execution through completion. **DO NOT PAUSE** between phases.
- Task description's "0.6 Pause and review" / "Operator review required" language is **superseded** by `convergence-map.md`.
- All D1–D10 decisions are LOCKED in `convergence-map.md` Part D. Do not re-litigate.

## Single optimization criterion

**Closely follow the shape of pi-mono.** When unsure, re-read the relevant section of `pi-mono-catalog.md` and match it. Naming, file layout, type structure, method signatures should be diffable line-for-line with pi-mono (modulo TS↔Python syntax — see D10 for the mapping rules).

## What's in this directory

- `pi-mono-catalog.md` (928L) — reference baseline. pi-mono SHA `3d9e14d7`. Every type, method, file laid out.
- `agent-hub-current.md` (860L) — current-state baseline of `backend/app/adapters/` (67 files) + `backend/app/api/complete/` (66 files). What's there now; what's theatre.
- `downstream-consumers.md` (359L) — the immutable HTTP/SSE contract. summitflow + portfolio-ai + vantage call sites; 25 routes; 9 SSE event types. **Do not break these.**
- `convergence-map.md` — synthesis. Part A pi-mono→agent-hub map, Part B agent-hub classification (KEEP/REMOVE/REPLACE/NEW), Part C NEW-REQUIREMENT justifications (C1–C10), Part D locked decisions (D1–D10), Part E phase-ordering refinements.
- `CONTINUATION.md` — this file.

## What's in `backend/app/llm/` today

After Phase 1+2:

```
backend/app/llm/
├── __init__.py
├── api_registry.py        # ApiProvider Protocol + registry (Phase 1.A)
├── env_api_keys.py
├── event_stream.py        # EventStream[T,R] + AssistantMessageEventStream
├── simple_options.py
├── stream.py              # stream/complete/stream_simple/complete_simple
├── tool_loop.py           # unified tool loop (Phase 1.D)
├── transform_messages.py
├── types.py               # universal types + 12-variant AssistantMessageEvent
├── providers/
│   ├── __init__.py
│   ├── anthropic.py       # Phase 1.C — reference port
│   ├── openai_completions.py  # Phase 2.1 — collapses xAI/OpenRouter/Kimi/...
│   ├── google.py          # Phase 2.2 — replaces 13 gemini_* files
│   ├── google_shared.py
│   ├── cloudflare.py      # Phase 2.3 — URL helpers only; provider via openai_completions
│   └── faux.py            # Phase 2.4 — test double
└── utils/
    ├── __init__.py
    ├── diagnostics.py
    ├── json_parse.py
    ├── overflow.py
    ├── sanitize_unicode.py
    ├── validation.py
    └── oauth/
        ├── __init__.py
        ├── anthropic.py   # Phase 1.B
        ├── pkce.py
        └── types.py
```

Plus `backend/app/api/complete/`:
- `orchestrator.py` (Phase 3.1) — `run_completion` / `run_completion_stream` / `build_context_from_messages` / `is_new_pipeline_enabled`
- `sse_writer.py` (Phase 1.D) — translates `AssistantMessageEvent` + tool-loop events into the 9-event downstream SSE contract

Tests at `backend/tests/llm/`: 11 passing across `test_pipeline_smoke.py`, `test_faux_provider.py`, `test_orchestrator.py`.

Registry on import contains: `anthropic-messages`, `openai-completions`, `google-generative-ai`. Faux is registered per-test via `register_faux_provider()`.

## Phase 3 — REMAINING (start here)

The orchestrator skeleton + feature flag are in place but **the HTTP route still uses the legacy `complete_orchestrator.py` + `complete_execution.py`**. Phase 3 finishes the harness collapse and flips the route.

1. **`backend/app/api/complete/session_repo.py`** — collapse `session_manager.py` (198L) + `_session_helpers.py` (162L) + `session_setup.py` (110L) into ONE module (~200L target per convergence-map.md C1). Load conversation history from DB → universal `list[Message]`; persist final `AssistantMessage` after a turn. **DB session loading/persistence stays where it is** (`backend/app/db/models/sessions.py`); only the helper layer collapses.

2. **`backend/app/routing/`** — new package collapsing `resolution.py` (383L) + the capability-routing parts of `adapters/registry.py` (per convergence-map.md C2, B1). Inputs: `agent_slug`, `workload_profile`, `task_type`, `cost_preference`, `routing_exclude_providers`. Output: ordered list of `Model[Api]` to try. Routing decisions are produced OUTSIDE the adapter; failed adapters surface as `AssistantMessage{ stop_reason: "error" }` and the router catches and tries the next.

3. **Memory move** — `memory_handler.py` → `backend/app/memory/` (per C4). Out-of-band citation extraction → `backend/app/memory/citation_extractor.py` (per D9). The adapter doesn't know about memory; the memory layer assembles the system prompt and post-processes the assistant message text for citations.

4. **HTTP route wiring** — `endpoints.py` `complete()` handler branches on `settings.llm_use_new_pipeline`:
   - True: call `orchestrator.run_completion(...)` or `orchestrator.run_completion_stream(...)` and translate to `CompletionResponse` / SSE.
   - False: existing `complete_orchestrator.execute_completion(...)` path (legacy).
   Also wire `async_endpoints.py` (the Hatchet workflow) and `cancel_stream()`.

5. **Block on green:** `st check` + at least one autocode E2E per consumer (agent-hub, summitflow, portfolio-ai). Verify SSE event names match `downstream-consumers.md` Section 6.

6. **Flip the flag** — set `llm_use_new_pipeline=True` in `config.py` default (or via env in production). Old code path remains accessible for one rollback cycle.

**Phase 3 commit cadence:** one collapse per commit. Order: 3.2 session_repo → 3.3 routing/ → 3.4 memory → 3.5 HTTP wiring + flag flip → 3.6 autocode E2E verification.

Below is the original Phase 1 plan, kept for reference:

## Phase 1 — DONE

Detailed pi-mono cross-references appear in `convergence-map.md` Part A. Detailed file layout is in `convergence-map.md` D1.

1. **`backend/app/llm/types.py`** — port `packages/ai/src/types.ts` (565L) verbatim per D10:
   - Message family discriminated union (`UserMessage`, `AssistantMessage`, `ToolResultMessage`, `Message = ...`)
   - Content blocks (`TextContent`, `ThinkingContent`, `ImageContent`, `ToolCall`)
   - `Usage`, `StopReason`, `Tool`, `Context`, `Model<TApi>`
   - `StreamOptions`, `SimpleStreamOptions`
   - `AssistantMessageEvent` 12-variant discriminated union
   - Compat overrides (`OpenAICompletionsCompat`, `AnthropicMessagesCompat`, etc.) — copy from pi-mono types.ts

2. **`backend/app/llm/event_stream.py`** — port `utils/event-stream.ts` (87L):
   - `EventStream[T, R]` async iterable with queue + backpressure + terminal-event resolution
   - `AssistantMessageEventStream(EventStream[AssistantMessageEvent, AssistantMessage])`
   - `create_assistant_message_event_stream()` factory

3. **`backend/app/llm/transform_messages.py`** — port `providers/transform-messages.ts` (220L):
   - `transform_messages(messages, model, normalize_tool_call_id=None)`
   - Image downgrade, thinking-block handling, tool-call ID normalization, synthetic tool results, error/abort filtering
   - Two-pass algorithm preserving cross-turn tool-call IDs

4. **`backend/app/llm/simple_options.py`** — port `providers/simple-options.ts` (50L):
   - `build_base_options(model, options, api_key)`
   - `clamp_reasoning(effort)`
   - `adjust_max_tokens_for_thinking(...)`

5. **`backend/app/llm/api_registry.py`** — port `api-registry.ts` (98L):
   - `ApiProvider` Protocol with exactly two methods: `stream`, `stream_simple`
   - Registry: `register_api_provider`, `get_api_provider`, `get_api_providers`, `unregister_api_providers`, `clear_api_providers`
   - Keyed by `api` string identifier

6. **`backend/app/llm/stream.py`** — port `stream.ts` (59L):
   - `async def stream(model, context, options)` → `AssistantMessageEventStream`
   - `async def complete(model, context, options)` → `AssistantMessage` (== `stream().result()`)
   - `async def stream_simple(...)`, `async def complete_simple(...)`
   - `get_env_api_key(provider)` re-export

7. **`backend/app/llm/env_api_keys.py`** — port `env-api-keys.ts` (210L):
   - Per-provider env var mapping
   - `get_env_api_key(provider)`, `find_env_keys(provider)`
   - Vertex ADC detection, Bedrock credential chain, Bun-style `/proc/self/environ` fallback NOT needed

8. **`backend/app/llm/utils/json_parse.py`**, **`overflow.py`**, **`diagnostics.py`**, **`validation.py`** — port the four utilities that providers depend on.

9. **`backend/app/llm/utils/oauth/`** — port pi-mono's `utils/oauth/` structure:
   - `types.py` — `OAuthProviderInterface`, `OAuthCredentials`, `OAuthLoginCallbacks`, `OAuthProviderId` (start with `"anthropic"`; add others in Phase 2)
   - `pkce.py` — `generate_code_verifier`, `generate_code_challenge`
   - `anthropic.py` — port `utils/oauth/anthropic.ts` (402L). Use existing agent-hub OAuth code as scaffolding; conform to pi-mono shape.
   - `__init__.py` — registry (`register_oauth_provider`, `get_oauth_provider`, `refresh_oauth_token`, `get_oauth_api_key`)

10. **`backend/app/llm/providers/anthropic.py`** — port `providers/anthropic.ts` (1207L). The reference port. Includes:
    - `AnthropicOptions(StreamOptions)` with `thinking_enabled`, `thinking_budget_tokens`, `effort`, `thinking_display`, `interleaved_thinking`, `tool_choice`
    - `create_client(model, api_key, ...)` (API key + OAuth + Copilot bearer)
    - `convert_messages(messages, model, is_oauth_token, cache_control)` (via `transform_messages`)
    - `build_params(model, context, is_oauth_token, options)`
    - `stream_anthropic(model, context, options)` — SSE state machine emitting `AssistantMessageEvent`s. **Native streaming only — NO `messages.create` without `stream=True` anywhere.**
    - `stream_simple_anthropic(model, context, options)` — maps `reasoning` level
    - Registration via `register_api_provider({api: "anthropic-messages", stream, stream_simple})` at module import

11. **`backend/app/llm/tool_loop.py`** — unified tool loop consuming `AssistantMessageEvent`. ~200L target. Replaces 5 sync + 4 streaming tool-loop files. Takes a tool-runner callback (the caller's responsibility to actually execute tools — same boundary as pi-mono's "tool execution is the caller's job"). The HTTP `execute_tools=True` path invokes `tool_loop.run(...)` with `backend/app/services/tools/` as the runner.

12. **`backend/app/api/complete/sse_writer.py`** — adapter from `AssistantMessageEvent` → SSE wire format (the 9-event downstream contract). Replaces `streaming_persistence.py` + `streaming_tool_messages.py` + parts of `streaming.py`. ~250L target. **Preserves the exact wire-event names and field shapes documented in `downstream-consumers.md` Section 6.** This is where the universal-shape internals meet the locked HTTP contract.

13. **Smoke test** — call the new pipeline through a unit test that exercises tools end-to-end against the new anthropic provider. Do NOT switch the HTTP route yet (Phase 3 does that). Just confirm: real Anthropic API → `stream_anthropic` → `AssistantMessageEvent` stream → `tool_loop` → tools execute → final `AssistantMessage` returned. Use a recent task's tool sequence from `git log` as a fixture.

**Phase 1 commit cadence:** items 1–8 can be one commit ("introduce universal types + registry"). Item 9 is one commit. Item 10 is one commit (the reference port). Items 11–13 are one commit ("unify tool loop + SSE writer"). Total ~4 commits.

**Phase 1 done when:** the new anthropic path passes a real-API smoke test producing equivalent assistant output to the current path on at least one multi-turn tool sequence. Old code untouched.

## Phase 2 — provider ports (one per commit)

After Phase 1 is green, port providers one at a time. Order:
1. `openai_completions.py` — collapses xAI, OpenRouter, Kimi, Moonshot, DeepSeek, Zhipu, Nvidia, Minimax, plus the 6 stubs. They are catalog entries on this single provider (per-Model `baseUrl` + `compat?`). Verify each works against its actual API.
2. `google.py` (+ `google_shared.py`) — replaces 13 `gemini_*` files. Probe whether `google_vertex.py` is needed for any catalog model; add only if so.
3. `cloudflare.py` — per D4, probe Workers AI wire format. If OpenAI-compat, collapse into `openai_completions.py` as a catalog entry instead. If not, add as single-file provider.
4. `faux.py` — port `providers/faux.ts` (499L). Replaces ad-hoc test mocking.

Bedrock, mistral, openai-responses, azure-openai-responses, openai-codex-responses: skip for v1 unless catalog (`backend/app/constants/catalog_entries.py`) actually references them. Verify; if no, document as deferred.

## Phase 3 — harness collapse

1. New unified orchestrator at `backend/app/api/complete/orchestrator.py` (collapses `complete_orchestrator.py` + `complete_execution.py`) that calls `backend/app/llm/stream.py` and `backend/app/llm/tool_loop.py`.
2. New `backend/app/api/complete/session_repo.py` (collapses `session_manager.py` + `_session_helpers.py` + `session_setup.py`). DB session loading/persistence stays.
3. Memory injection moves to `backend/app/memory/` (was `memory_handler.py`).
4. Citation extraction moves to `backend/app/memory/citation_extractor.py` (out-of-band per D9).
5. Routing moves to `backend/app/routing/` (was `resolution.py` + parts of `adapters/registry.py`).
6. Flip the HTTP routes (`POST /api/complete`, `POST /api/complete/cancel`, async endpoints) to call the new orchestrator. Add a feature flag `LLM_USE_NEW_PIPELINE` (default ON) that allows reverting to the old path if a downstream regression appears. Removed in Phase 5.
7. **Block on green:** run `st check` + at least one autocode E2E per consumer (agent-hub, summitflow, portfolio-ai). Check SSE event names match the downstream contract.

## Phase 4 — delete old surfaces

After Phase 3 is green for a few days of real autocode runs:
1. Delete `backend/app/adapters/` (except image adapters which are out of scope).
2. Delete the old pipeline files in `backend/app/api/complete/` listed as REMOVE-THEATRE in `convergence-map.md` Part B.
3. Sweep for orphans with `vulture` + manual grep on the listed types (`CompletionResult` 4-way, `ToolEvent`, `_ExecutionState`, `ToolExecutionResult`, `StreamFromComplete`, `ProviderRuntimeSession`, `RuntimeSessionRegistry`, `AgentProgressInfo` if merged with `AgentProgress`).
4. Remove the `LLM_USE_NEW_PIPELINE` feature flag.
5. Update tests to consume the new shape.
6. Block on green: full test suite + autocode E2E per project.

## Phase 5 — guardrails

1. `backend/tests/architecture/test_pimono_shape.py` per D8 (AST checks for the shape constraints).
2. `import-linter` rules per D8 (add to existing tooling stack).
3. `backend/docs/adr/0001-pi-mono-single-universal-adapter.md`. References this directory + `pi-mono-catalog.md`.
4. Agent-hub memory mandate: "Single universal adapter — never branch the surface." Sticky, high-confidence.
5. Periodic re-audit script `backend/scripts/audit_pimono_drift.py` that pulls latest pi-mono and reports new primitives we should adopt + any new agent-hub types that don't map.

## Done-when criteria

- `backend/app/llm/` exists with the two-method `ApiProvider`, `AssistantMessageEvent`-based stream, and registry.
- Every provider is exactly one file (with at most the pi-mono-precedented shared-helpers).
- `ProviderAdapter`, `CompletionResult` (all 4 variants), `ToolEvent`, `StreamEvent`, `_ExecutionState`, `ToolExecutionResult`, `ProviderRuntimeSession`, `RuntimeSessionRegistry` are all gone.
- Tool loop is one pipeline (`backend/app/llm/tool_loop.py`). Session abstraction is `session_repo.py`. `CompletionResult` shape is defined once as `AssistantMessage` in `backend/app/llm/types.py`.
- Total file count in `backend/app/llm/` + `backend/app/api/complete/` is within ~2× of pi-mono's in-scope hand-written surface (target: ~38 files / ~8,300 LOC vs pi-mono's ~42 files / ~12,624 LOC).
- agent-hub + summitflow + portfolio-ai all run autocode E2E through the new pipeline on at least one trivial-tier task per project.
- Architectural test + ADR + memory mandate + periodic re-audit script are all in place.

## Process rules (carry forward)

- **Continuously cross-check pi-mono.** Every design decision answers "how does pi-mono do this?" If the answer diverges, document the divergence in this map's Part D or in the per-phase commit body.
- **No subagent fan-out for sequential work.** Phase 2 provider ports CAN parallelize across providers (different providers don't touch each other's code), but Phase 1 items 1–13 are sequential.
- **One provider per commit in Phase 2. One harness collapse per commit in Phase 3.** Phase 4 deletions can batch.
- **Theatre removal is MANDATORY.** Anything without a clear job and a clear pi-mono analogue (or a Part C-style justified divergence) gets DELETED in Phase 4, not parked "just in case".
- **No half-finished implementations** — see CLAUDE.md global rules. Each phase commit should leave the codebase green or with the failure clearly attributable to the next subtask.
- **No `--no-verify`** to bypass hooks. Fix the root cause.
- **Commit via `st commit`** (the canonical commit wrapper). Quality gates via `st check`. Browser checks via `st browser` if needed. Never raw `git commit`, `pytest`, `ruff`, etc.

## Continuation prompt

If a future session loses context (e.g., after `/clear`), the operator should re-enter with:

```
Resume task-e65e9ee0. Read backend/tasks/agent-framework-convergence/CONTINUATION.md, then continue autonomously per the directive in convergence-map.md. Do not pause for review.
```
