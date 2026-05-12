# Agent-Hub Downstream Consumer Contracts — Audit Catalog

**The outer boundary of the convergence refactor.** Generated as Phase 0.4 of task `task-e65e9ee0`.

- **Scope:** every project that calls into agent-hub's HTTP API, with the full request/response contract they depend on
- **Consumers found:** `summitflow`, `portfolio-ai`, `vantage`
- **Out of scope:** `a-term`, `a_term`, `monkey-fight`, `test1/2/3`, `sha`, agent-hub's own internal callers (verified no direct API calls)

> Every contract documented here must be preserved through the convergence refactor (or explicitly renegotiated with the operator before changing). These contracts are the immutable wall between agent-hub internals and downstream consumers.

---

## 1. Agent-hub HTTP API surface

### Router: `backend/app/api/complete/endpoints.py`

#### `POST /api/complete`
- **Handler:** `complete()` @ `endpoints.py:32`
- **Request model:** `CompletionRequest` (`request_schemas.py`)
- **Auth:** `X-Client-Id` + `X-Request-Source` headers (enforced by `AccessControlMiddleware`); `X-Skip-Cache` header bypasses response cache
- **Branches:**
  - `stream=True` → `StreamingResponse` (SSE)
  - `stream=False, async_execution=False` → `JSONResponse(CompletionResponse)`
  - `async_execution=True` (agentic) → 202 with `AsyncTaskResponse`

**`CompletionRequest` key fields** (~30 fields, mostly optional):
- Required: `messages: list[MessageInput]`, `project_id: str`
- Identity: `agent_slug?`, `session_id?`, `parent_session_id?`, `external_id?`, `trace_id?`
- Control: `stream: bool`, `execute_tools: bool`, `max_turns: int`, `temperature: float`, `async_execution: bool`, `enable_caching: bool`, `cache_ttl: str`
- Tools / scope: `tools?: list[ToolDefinition]`, `tool_catalog?`, `use_memory: bool`, `thinking_level?`, `response_format?`, `read_only: bool`, `disable_agent_fallbacks: bool`
- Routing: `routing_mode_override?`, `routing_exclude_providers?`, `routing_cost_preference?`, `adhoc: bool`, `adhoc_spec?: AdhocWorkSpec`, `workload_profile?`, `task_type?`
- Context: `source_metadata?: SourceMetadata`, `work_context?: WorkContext`, `include_roles?`, `prompt_mode?`, `container_id?`, `memory_variant_override?`, `working_dir?`, `current_branch?`

**`CompletionResponse` fields (non-streaming):**
- `content: str`, `model: str`, `provider: str`
- `usage: UsageInfo`, `context_usage?: ContextUsageInfo`, `output_usage?: OutputUsageInfo`
- `session_id: str`, `finish_reason?: str`, `from_cache: bool`
- `thinking?: ThinkingInfo`, `tool_calls?: list[ToolCallInfo]`, `container?: ContainerInfo`
- `memory_facts_injected: int`, `memory_uuids?: str`, `cited_uuids: list[str]`
- `agent_used?: str`, `model_used?: str`, `fallback_used: bool`, `fallback_reason?: str`
- `turns: int`, `tool_calls_count: int`, `progress_log?: list[AgentProgressInfo]`
- `error_summary?: dict`, `trace_id?: str`
- Routing fields: `routing_mode?`, `workload_profile?`, `routing_decision_id?`, `auto_candidate_model_id?`, `routing_canary_percent?`

**SSE event protocol (when `stream=True`):**
- Wire format: `data: {json}\n\n` (newline-delimited JSON chunks)
- Media type: `text/event-stream`
- **Event types emitted via `StreamingChunk`:**

| Event `type`           | Required fields                                                                                                   | Optional fields |
|------------------------|-------------------------------------------------------------------------------------------------------------------|-----------------|
| `connected`            | `seq, session_id`                                                                                                 | `model, provider` |
| `content`              | `seq, content`                                                                                                    | `input_tokens, output_tokens, model, provider, session_id, agent_used, model_used, fallback_used, routing_mode, workload_profile, routing_decision_id, auto_candidate_model_id, routing_canary_percent` |
| `thinking`             | `seq, content`                                                                                                    | — |
| `tool_use`             | `seq, tool_id, tool_name, tool_input`                                                                             | — |
| `tool_start`           | `seq, tool_id, tool_name`                                                                                         | — |
| `tool_result`          | `seq, tool_id, tool_result, tool_status` (running/complete/error)                                                 | — |
| `cancel_acknowledged`  | `seq, session_id`                                                                                                 | — |
| `done`                 | `seq, finish_reason, input_tokens, output_tokens, cost_usd, model, provider, session_id`                          | `thinking_tokens, cache_read_tokens, cache_write_tokens, agent_used, model_used, fallback_used, routing_mode, workload_profile, routing_decision_id, auto_candidate_model_id, routing_canary_percent` |
| `error`                | `seq, error`                                                                                                      | `model, provider, session_id` |

**9 SSE event types** total. Every event carries a monotonic `seq: int`. Producers: `streaming.py`, `streaming_runtime_session.py`, `streaming_tool_executor.py`, `streaming_persistence.py`.

#### `POST /api/complete/cancel`
- **Handler:** `cancel_stream()` @ `endpoints.py:52`
- **Request:** `CancelStreamRequest{session_id: str}`
- **Response:** `{cancelled: bool, session_id: str}`
- **Behavior:** Signals backend abort event. Non-blocking. Stream finishes current tool, then halts.

#### `POST /api/estimate`
- **Handler:** `estimate()` @ `endpoints.py:66`
- **Request:** `EstimateRequest{model: str, messages: list[MessageInput]}`
- **Response:** `EstimateResponse{input_tokens, estimated_output_tokens, total_tokens, estimated_cost_usd, context_limit, context_usage_percent, context_warning?}`

### Router: `backend/app/api/complete/async_endpoints.py`

#### `GET /api/complete/tasks/{task_id}`
- **Handler:** `get_task_status()` @ `async_endpoints.py:60`
- **Response:** `AsyncTaskStatusResponse{task_id, session_id?, status, result?: CompletionResponse, error?, progress?}`
- **`status` enum:** `pending | started | completed | failed | cancelled | unknown`

#### `DELETE /api/complete/tasks/{task_id}/cancel`
- **Handler:** `cancel_task()` @ `async_endpoints.py:102`
- **Response:** `{task_id: str, status: str}`

### Router: `backend/app/api/agents.py`

| Route | Method | Body | Response | Purpose |
|-------|--------|------|----------|---------|
| `/api/agents` | GET | `?active_only, ?is_coding_agent, ?limit, ?offset` | `AgentListResponse{agents: list[AgentResponse]}` | List agents |
| `/api/agents/{slug}` | GET | — | `AgentResponse` | Get agent |
| `/api/agents` | POST | `AgentCreateRequest` | `AgentResponse` (201) | Create agent |
| `/api/agents/{slug}` | PUT | `AgentUpdateRequest` | `AgentResponse` | Update |
| `/api/agents/{slug}` | DELETE | — | 204 | Delete |
| `/api/agents/{slug}/preview` | GET | `?project_id, ?task_type, ?phase, ?task_prompt` | `AgentPreviewResponse` | Preview agent context |
| `/api/agents/{slug}/routing` | GET | — | `AgentRoutingResponse` | Get routing config |
| `/api/agents/{slug}/routing` | PUT | `AgentRoutingUpdateRequest` | `AgentRoutingResponse` | Update routing |
| `/api/agents/{slug}/routing/workloads/{workload_profile}` | PUT | `AgentWorkloadRoutingUpdateRequest` | `AgentRoutingResponse` | Per-workload routing |
| `/api/agents/{slug}/metrics` | GET | — | `AgentMetrics` | Per-agent metrics |
| `/api/agents/metrics/all` | GET | — | `AgentMetricsListResponse` | All metrics |
| `/api/agents/{slug}/benchmarks` | GET | — | `AgentBenchmarkDashboard` | Benchmark dashboard |
| `/api/agents/{slug}/benchmarks/{run_id}` | GET | — | `AgentBenchmarkRunDetail` | Per-run detail |
| `/api/agents/{slug}/versions` | GET | — | versions list | Agent versions |

### Router: `backend/app/api/sessions.py`

| Route | Method | Body | Response | Purpose |
|-------|--------|------|----------|---------|
| `/api/sessions` | POST | `SessionCreate` | `SessionResponse` (201) | Create session |
| `/api/sessions/{session_id}` | GET | — | `SessionResponse` | Get session |
| `/api/sessions/{session_id}/events` | GET | `?event_type, ?turn, ?page, ?page_size` | `SessionEventsResponse{session_id, events, total, max_turn}` | List session events |
| `/api/sessions/{session_id}/events` | POST | `CreateSessionEventRequest` | `CreateSessionEventResponse{event_id, session_id, sequence}` (201) | Record session event |
| `/api/sessions/{session_id}/heartbeat` | POST | `SessionHeartbeatRequest` | `SessionResponse` | Heartbeat |
| `/api/sessions/{session_id}` | DELETE | — | 204 | Delete |
| `/api/sessions` | GET | `?project_id, ?status, ?agent_slug, ?parent_session_id, ?session_type, ?external_id, ?page, ?page_size` | `SessionListResponse{sessions, total, page, page_size}` | List sessions |
| `/api/sessions/{session_id}/close` | POST | — | `CloseSessionResponse{id, status, message}` | Close (idempotent) |
| `/api/sessions/{session_id}/fork` | POST | `SessionForkRequest{fork_at_turn}` | `SessionForkResponse` (201) | Fork for A/B |
| `/api/sessions/{session_id}/promote` | POST | `SessionPromoteRequest{promote_to_branch?}` | `SessionPromoteResponse` | Promote a branch |

### WebSocket: `backend/app/api/events.py`

#### `WS /api/events`
- **Handler:** `events_websocket()` @ `events.py:131`
- **Protocol:**
  - Client sends: `{"type": "subscribe", "session_ids": [...], "event_types": [...]}` → server `{"type": "subscribed", "subscription_id": "..."}`
  - Client sends: `{"type": "update", "session_ids": [...], "event_types": [...]}` → server `{"type": "updated", "subscription_id": "..."}`
  - Client sends: `{"type": "unsubscribe"}` → server `{"type": "unsubscribed", "message": "..."}`, then close code 1000
- After subscription: server pushes `SessionEvent` objects as JSON (shape depends on `event_type` from `SessionEventType` enum)

### Other completion/tool/agent-related routers (brief)

- `GET /api/ownership/projects/{project_id}/live` — live ownership inventory
- `GET /api/models` — list available models
- `GET /api/orchestration/health` — orchestration health check
- `GET /api/analytics/cost-logs?project_id=...&limit=...` — cost analytics

---

## 2. SummitFlow — every call into agent-hub

### File: `summitflow/backend/cli/commands/_complete_http.py`

Primary HTTP client wrapper for completion calls.

**Functions:**
- `build_payload()` @ line 79 — builds `CompletionRequest` body
- `stream_complete()` @ line 142 — SSE parser
- `call_complete()` @ line 212 — non-streaming wrapper

**Request payload keys sent:**
`project_id, messages, agent_slug, memory_group_id, working_dir, session_id, thinking_level, trace_id, use_memory, execute_tools, task_type, max_turns, stream, include_roles, source_metadata, work_context, read_only, adhoc, adhoc_spec, routing_exclude_providers, routing_cost_preference, parent_session_id`

**SSE parsing in `stream_complete()`:**
- Reads lines starting with `data: ` → JSON parse
- Switches on `type` field
- Consumed events: `content, thinking, tool_use, tool_start, tool_result, done, error`
- Per-event fields read: `content, seq, finish_reason, input_tokens, output_tokens, tool_id, tool_name, tool_input, tool_result, tool_status, cost_usd, cache_read_tokens, cache_write_tokens, model, provider, session_id`

### File: `summitflow/backend/app/api/agent_hub.py`

Backend proxy from SummitFlow's HTTP service to agent-hub.

| Function | File:line | Proxies to |
|----------|-----------|------------|
| `list_coding_agents()` | line 142 | `GET /api/agents` (with `is_coding_agent=true`) |
| `list_models()` | line 162 | `GET /api/models` |
| `get_preferences()` | line 173 | `GET /api/preferences` |
| `update_preferences()` | line 179 | `PUT /api/preferences` |
| `list_agent_hub_sessions()` | line 204 | `GET /api/sessions?project_id, status, agent_slug, parent_session_id, page, page_size` |
| `get_session()` | line 229 | `GET /api/sessions/{session_id}` |
| `close_session()` | line 235 | `POST /api/sessions/{session_id}/close` |
| `get_project_live_ownership()` | line 253 | `GET /api/ownership/projects/{project_id}/live` |
| `proxy_complete()` | line 301 | `POST /api/complete` (streams SSE through to frontend as `StreamingResponse(media_type="text/event-stream")`) |

### CLI commands that hit agent-hub

| CLI command | Entrypoint file | Endpoints hit |
|-------------|-----------------|---------------|
| `st complete` | `cli/commands/complete.py` (calls `call_complete()`) | `POST /api/complete` |
| `st autocode` | `cli/commands/tasks_autocode.py` | `POST /api/complete` (async dispatch) |
| `st autonomous` | `cli/commands/autonomous.py` | `POST /api/complete` (streaming) |
| `st sessions` | `cli/commands/sessions.py` (via `_client_execution.py:get_session()`) | `GET /api/sessions`, `GET /api/sessions/{id}` |
| `st agent` | `cli/commands/agent.py` (via `cli/commands/agents_api.py`) | `GET /api/agents`, `GET /api/agents/{slug}`, `GET /api/agents/{slug}/routing`, etc. |
| `st claude` | (various) | `POST /api/complete` (with `agent_slug=claude-code`) |
| `st memory` | (memory routes) | not in convergence scope |

---

## 3. portfolio-ai — every call into agent-hub

### File: `portfolio-ai/backend/app/agents/clients/agent_hub_client.py` (~350L)

Uses the canonical `agent_hub` Python SDK (not direct HTTP).

**`AgentHubAPIClient` class:**
- `__init__()` @ line 43 — initializes `SDKClient` (from `agent_hub import AgentHubClient as SDKClient`)
- `generate()` @ line 121 — convenience wrapper that calls `complete_messages()`
- `complete_messages()` @ line 219 — main entry

**`complete_messages()` request keys sent:**
`agent_slug, messages, temperature, project_id, purpose, tools, use_memory, session_id, max_turns, thinking_level, response_format, system_prompt, execute_tools, enable_programmatic_tools`

**Response fields consumed:**
`response.content, response.provider, response.model, response.usage (input_tokens, output_tokens, total_tokens, cache info), response.finish_reason, response.session_id, response.from_cache, response.tool_calls`

### Other portfolio-ai consumers

| File | Endpoint hit | Purpose |
|------|-------------|---------|
| `backend/app/services/household_review_agent_service.py` | `GET /api/agents/{HOUSEHOLD_REVIEW_AGENT_SLUG}` | Agent slug lookup for review agent |
| `backend/app/services/agent_hub_prompt_service.py` | `GET /api/agents/{slug}` and preview | Load agent prompt configs |
| `backend/app/agents/committee/stages.py` | `POST /api/complete` (via SDK + `generate()`) | Committee-stage completions |

---

## 4. vantage — every call into agent-hub

### File: `vantage/backend/app/adapters/agent_hub.py` (~134L)

`AgentHubAdapter` implements vantage's `AgentBackend` protocol.

| Method | File:line | Endpoint hit | Notes |
|--------|-----------|-------------|-------|
| `verify_registration()` | line 42 | `GET /api/projects/{project_id}/execution-permission` + `GET /api/analytics/cost-logs?project_id=...&limit=1` | Pre-flight check |
| `run_agent()` | line 56 | `POST /api/complete` with `async_execution=true` | Async dispatch; payload keys `agent_slug, project_id, messages, external_id, trace_id, max_turns, execute_tools, async_execution=true`; reads `task_id, session_id, status` from `AsyncTaskResponse` |
| `get_run_status()` | line 79 | `GET /api/complete/tasks/{task_id}` | Polls; reads `status, session_id, payload` |
| `list_agent_runs()` | line 91 | `GET /api/sessions?project_id, agent_slug, ...` | Reads `sessions[].id, status, external_id, provider_metadata.trace_id, agent_slug, project_id` |
| `complete()` | line 113 | `POST /api/complete` (non-async, non-streaming) | Reads `content, session_id, model, provider, full payload` |

---

## 5. Other potential consumers

| Project | Direct agent-hub call? | Notes |
|---------|------------------------|-------|
| `a-term`, `a_term` | No | Only test mocks / config references |
| `monkey-fight` | No | Verified clean grep |
| `vantage` | YES — see Section 4 | Async run dispatch |
| `test1`, `test2`, `test3` | No | Scratch dirs |
| `sha`, `public-release-plan.md` | No | Not project dirs |
| Agent-hub itself | No internal API self-calls | All internal calls bypass HTTP via direct function calls |

---

## 6. Event-shape contract (the most fragile interface)

Distinct SSE event names emitted by agent-hub and the consumers that parse each one:

| Event | Producer file | Consumers (file:line ranges) | Payload keys consumers depend on |
|-------|---------------|------------------------------|-----------------------------------|
| `connected` | `streaming.py` | SummitFlow frontend (internal ACK) | `type, seq, session_id, model, provider` |
| `content` | `streaming_runtime_session.py`, `streaming.py` | `_complete_http.py:stream_complete`, SummitFlow frontend, portfolio-ai (via SDK) | `type, seq, content, input_tokens, output_tokens, model, provider, session_id, agent_used, model_used, fallback_used, routing_mode, workload_profile, routing_decision_id, auto_candidate_model_id, routing_canary_percent` |
| `thinking` | `streaming_runtime_session.py` | SummitFlow frontend, `_complete_http.py` | `type, seq, content` |
| `tool_use` | `streaming_runtime_session.py` | SummitFlow frontend, `_complete_http.py` | `type, seq, tool_id, tool_name, tool_input` |
| `tool_start` | `streaming_tool_executor.py` | SummitFlow frontend | `type, seq, tool_id, tool_name` |
| `tool_result` | `streaming_tool_executor.py` | SummitFlow frontend, `_complete_http.py` | `type, seq, tool_id, tool_result, tool_status` |
| `cancel_acknowledged` | `streaming_tool_executor.py` | SummitFlow frontend | `type, seq, session_id` |
| `done` | `streaming_persistence.py` | `_complete_http.py`, SummitFlow frontend, portfolio-ai (via SDK) | `type, seq, finish_reason, input_tokens, output_tokens, cost_usd, thinking_tokens, cache_read_tokens, cache_write_tokens, model, provider, session_id` + routing fields |
| `error` | `streaming.py`, `streaming_tool_executor.py` | `_complete_http.py`, SummitFlow frontend | `type, seq, error, model?, provider?, session_id?` |

**9 distinct SSE event types.** Adding new types is backwards-compatible (consumers ignore unknown). Renaming or removing types or required fields is BREAKING.

---

## 7. Recent contract changes

`git log --oneline -30 -- backend/app/api/complete/ backend/app/api/agents.py` shows internal-only churn:

| Commit | Nature | Contract impact |
|--------|--------|-----------------|
| 820670c8 | Internal: max_tokens from catalog | No contract change |
| c86f926f | Internal: remove default timeout | No contract change |
| 773dc973 | Internal: timeout logic | No contract change |
| 6036c5f7 | Internal: dedup tool results | No contract change |
| e3671a12 | Internal: cancellation | No contract change |
| 11f5767c | Internal: adaptive routing | No contract change |
| db963140 | **ADDED** `adhoc, adhoc_spec` to `CompletionRequest` | Backwards-compatible (optional, defaults False/None) |
| dc37be6b | Work Chats feature | Possibly added new session_type values or routing modes |
| 41e43ca2 | Streaming refactor | Internal reorganization, no event shape change |

**Recent backward-compatible additions to `CompletionRequest`:**
- `adhoc: bool`, `adhoc_spec?: AdhocWorkSpec`
- `async_execution: bool` (for async task dispatch)
- `routing_exclude_providers?`, `routing_cost_preference?`, `routing_mode_override?`, `routing_canary_percent?`, `disable_agent_fallbacks: bool`

All landed as optional fields with sensible defaults — no consumers broke.

---

## 8. Risk hotspots

### High-risk contracts (highest priority to preserve)

1. **SSE event names and required fields** (Section 6). Each consumer parses by exact string match on `type` and accesses payload by exact key. **Cannot rename, cannot remove.**

2. **`async_execution` task contract** — vantage's full async dispatch depends on:
   - `POST /api/complete` with `async_execution=true` returning `AsyncTaskResponse{task_id, session_id, status, poll_url, events_channel, trace_id?}`
   - `GET /api/complete/tasks/{task_id}` returning status enum `pending | started | completed | failed | cancelled | unknown`
   - **Status enum is the most fragile** — adding values is OK, renaming/removing breaks polling.

3. **Session ID + parent_session_id continuity** — SummitFlow CLI commands chain sessions across turns; fork/promote semantics must remain stable.

4. **Routing decision audit trail** — `routing_decision_id, routing_mode, workload_profile, auto_candidate_model_id, routing_canary_percent` are logged by callers for cost/quality reporting. Format/persistence must be stable.

5. **Agent slug semantics** — agents are referenced by slug everywhere. Changing slug format or routing per-slug breaks every consumer's stored config.

6. **Memory tracking fields** — `memory_facts_injected, memory_uuids, cited_uuids` are used for observability/attribution. Field removal breaks audit pipelines.

### Moderate-risk contracts

7. **`ToolCallInfo` shape** in non-streaming responses (`{id, name, input, caller_type, caller_tool_id}`) — callers loop tool calls.

8. **`ContextUsageInfo` and warning messages** — consumers display these in UI. Format change is visible but recoverable.

9. **`finish_reason` enum values** — currently free-form string; consumers may switch on specific values.

### Low-risk

10. Workload profiles + routing modes — admin-defined; adding values is safe.

---

## 9. Counts

| Metric | Count |
|--------|-------|
| Total routes touching completion / tool / agent flow | 25 (3 completion + 2 async task + 11 agents + 8 sessions + 1 WebSocket) |
| Distinct SSE event names | 9 |
| Distinct downstream call sites (across SummitFlow + portfolio-ai + vantage) | ~16–20 |
| `CompletionRequest` fields (most optional) | 30+ |
| Status enum values for async tasks | 6 (`pending, started, completed, failed, cancelled, unknown`) |

---

## 10. Summary — contracts that MUST survive convergence

The convergence refactor MAY rebuild every internal pipeline, but MUST preserve:

1. **All 25 HTTP route paths and methods.** Renaming routes = silent 404 for every consumer.
2. **All Pydantic request/response model field names and types** (additions OK, removals/renames not OK).
3. **All 9 SSE event names and their required payload fields.**
4. **Session ID, task ID, agent slug, routing decision ID semantics.**
5. **Async task status enum** (`pending|started|completed|failed|cancelled|unknown`).
6. **WebSocket subscription protocol** (`subscribe / update / unsubscribe` with `session_ids` + `event_types`).
7. **`AgentHubClient` Python SDK shape** (portfolio-ai depends on the SDK's `complete_messages()` method signature; if the SDK is rebuilt around new internals, its public surface must remain).

**Permitted changes** (still operator-approved per task rules):
- Add new optional `CompletionRequest` fields with defaults
- Add new SSE event types (existing types must keep emitting unchanged)
- Add new response fields (defaults must keep older clients working)
- Add new endpoints

**Forbidden without explicit renegotiation:**
- Rename any route / field / event type
- Remove any route / field / event type
- Change a field's type
- Change `finish_reason` values that callers may switch on
- Change the SSE wire format (e.g., switching from `data:` framing to plain JSON)
- Change semantics of fork/promote without versioning
