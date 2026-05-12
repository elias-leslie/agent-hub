# CONTINUATION — task-e65e9ee0

**Read this file first. Then `pi-mono-catalog.md` and `convergence-map.md`. Then begin Phase 1.**

## Status

- Phase 0 (audit): **COMPLETE** — committed in the same git commit that introduced this directory.
- Phase 1 (build new shape, port anthropic as reference): **NEXT — start here**.
- Operator has approved autonomous execution through completion. **DO NOT PAUSE** between phases or subtasks.
- The task description's "0.6 Pause and review" / "Operator review required" language is **superseded** by `convergence-map.md` § "STATUS — OPERATOR-APPROVED, AUTONOMOUS EXECUTION" and § "Autonomous-execution directive".
- All D1–D10 decisions are LOCKED in `convergence-map.md` Part D. Do not re-litigate.

## Single optimization criterion

**Closely follow the shape of pi-mono.** When unsure, re-read the relevant section of `pi-mono-catalog.md` and match it. Naming, file layout, type structure, method signatures should be diffable line-for-line with pi-mono (modulo TS↔Python syntax — see D10 for the mapping rules).

## What's in this directory

- `pi-mono-catalog.md` (928L) — reference baseline. pi-mono SHA `3d9e14d7`. Every type, method, file laid out.
- `agent-hub-current.md` (860L) — current-state baseline of `backend/app/adapters/` (67 files) + `backend/app/api/complete/` (66 files). What's there now; what's theatre.
- `downstream-consumers.md` (359L) — the immutable HTTP/SSE contract. summitflow + portfolio-ai + vantage call sites; 25 routes; 9 SSE event types. **Do not break these.**
- `convergence-map.md` — synthesis. Part A pi-mono→agent-hub map, Part B agent-hub classification (KEEP/REMOVE/REPLACE/NEW), Part C NEW-REQUIREMENT justifications (C1–C10), Part D locked decisions (D1–D10), Part E phase-ordering refinements.
- `CONTINUATION.md` — this file.

## Phase 1 — START HERE

Build the new `backend/app/llm/` shape and port Anthropic as the reference. Files go in the order below; each is a single commit.

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
