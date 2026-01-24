# Agent Hub Comprehensive Plan

**Project:** Agent Hub - Unified Agentic AI Service
**Goal:** Fully flesh out Agent Hub with proper agent_slug enforcement, remove artificial caps, consolidate streaming endpoints, and complete all frontend pages.

---

## Executive Summary

### Current State
- Backend: 17 API endpoint files (~9000 lines), FastAPI + PostgreSQL + Redis
- Frontend: 20 pages, Next.js 16 + React 19
- Python SDK: sync/async clients with partial agent_slug support
- Issues identified during exploration (see sections below)

### Key Problems to Solve
1. **Artificial max_tokens capping** - Our code sets arbitrary defaults that truncate responses
2. **Duplicate streaming endpoints** - WebSocket `/api/stream` vs SSE `/api/complete?stream=true`
3. **Incomplete agent_slug support** - Only `/api/complete` fully implements it
4. **Frontend stubs** - `/analytics` page is a redirect, agent analytics uses mock data
5. **SDK gaps** - Missing agent_slug in several client methods

### Design Principles
- **No artificial caps** - Let external models use their own defaults
- **Single streaming endpoint** - Consolidate to `/api/complete?stream=true`
- **agent_slug everywhere** - Required for all agent-related operations
- **Complete UI** - Every page fully functional with real data

---

## Part 1: Remove Artificial Max Token Caps

### Problem
Our code sets arbitrary `max_tokens` defaults that truncate responses:
- `_DEFAULT_MAX_TOKENS = 8192` in base.py
- `OUTPUT_LIMIT_CHAT = 4096` in constants.py
- Various adapter method defaults of 4096

### Research Findings

**Claude API:**
- `max_tokens` is REQUIRED - API errors if omitted
- We MUST pass a value to Claude
- Best approach: Pass model's actual max (64000 for Claude 4.5)

**Gemini API:**
- `max_output_tokens` is OPTIONAL
- If omitted, Gemini uses intelligent model-specific defaults
- Best approach: Don't pass max_tokens unless user explicitly specifies

### Solution

#### 1.1 Update Adapter Signatures
**Files:** `backend/app/adapters/base.py`, `claude.py`, `gemini.py`

Change signature from:
```python
async def complete(..., max_tokens: int = 8192, ...)
```
To:
```python
async def complete(..., max_tokens: int | None = None, ...)
```

#### 1.2 Update Claude Adapter
**File:** `backend/app/adapters/claude.py`

When max_tokens is None, use model's actual maximum:
```python
effective_max_tokens = max_tokens if max_tokens is not None else 64000  # Claude 4.5 max
```

#### 1.3 Update Gemini Adapter
**File:** `backend/app/adapters/gemini.py`

When max_tokens is None, DON'T pass to Gemini - let it use its own default:
```python
config = types.GenerateContentConfig(
    temperature=temperature,
    # Only set max_output_tokens if explicitly specified
    **({"max_output_tokens": max_tokens} if max_tokens is not None else {}),
)
```

#### 1.4 Update API Endpoint Defaults
**Files:** `backend/app/api/complete.py`, `stream.py`

Change from:
```python
max_tokens: int = Field(default=OUTPUT_LIMIT_CHAT, ...)
```
To:
```python
max_tokens: int | None = Field(default=None, description="Max tokens (None = model default)")
```

#### 1.5 Remove/Update Constants
**File:** `backend/app/constants.py`

Keep OUTPUT_LIMITS for telemetry/debugging (model capabilities lookup).
Remove use-case specific defaults that encourage capping:
- `OUTPUT_LIMIT_CHAT = 4096` - REMOVE
- `OUTPUT_LIMIT_CODE = 16384` - REMOVE
- `OUTPUT_LIMIT_ANALYSIS = 32768` - REMOVE
- Keep `OUTPUT_LIMIT_AGENTIC = 64000` only as documentation of Claude max

#### 1.6 Update SDK Client
**File:** `packages/agent-hub-client/agent_hub/client.py`

Change `max_tokens` default from 8192 to None in all methods.

### Files to Modify
- `backend/app/adapters/base.py`
- `backend/app/adapters/claude.py`
- `backend/app/adapters/gemini.py`
- `backend/app/api/complete.py`
- `backend/app/api/stream.py` (before deprecation)
- `backend/app/constants.py`
- `backend/app/services/completion.py`
- `backend/app/services/token_counter.py`
- `packages/agent-hub-client/agent_hub/client.py`

---

## Part 2: Consolidate Streaming to /api/complete

### Problem
Two streaming endpoints exist:
- **WebSocket `/api/stream`** (884 lines) - Limited agent routing, bidirectional
- **SSE `/api/complete?stream=true`** - Full agent routing, simpler

WebSocket explicitly warns: "Full agent routing (mandates, fallbacks) requires SSE via POST /api/complete?stream=true"

### Impact Analysis

**What uses WebSocket /api/stream:**
1. Frontend: `frontend/src/hooks/use-chat-stream.ts` (367 lines)
2. SDK: `AsyncAgentHubClient.stream()` method
3. Tests: `test_stream.py`, `test_stream_cancel.py`, SDK streaming tests
4. Docs: API guide, feature parity docs

**What would break:**
- Frontend chat UI streaming
- SDK `stream()` method
- ~200 lines of tests

**Migration effort:** Medium (300 lines frontend, SDK updates)

### Solution

#### 2.1 Deprecate /api/stream Endpoint
**File:** `backend/app/api/stream.py`

Add deprecation warning at top of endpoint:
```python
@router.websocket("/stream")
async def stream_completion(websocket: WebSocket) -> None:
    """DEPRECATED: Use POST /api/complete with stream=true instead."""
    logger.warning("DEPRECATED: /api/stream - use /api/complete?stream=true")
    # ... existing code
```

#### 2.2 Update Frontend to Use SSE
**File:** `frontend/src/hooks/use-chat-stream.ts`

Replace WebSocket implementation with EventSource/fetch + SSE:
```typescript
// Before: WebSocket
const ws = new WebSocket(getWsUrl("/api/stream"));

// After: SSE via fetch
const controller = new AbortController();
const response = await fetch(buildApiUrl("/api/complete"), {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ ...request, stream: true }),
  signal: controller.signal,
});

const reader = response.body.getReader();
// ... process SSE chunks
```

#### 2.3 Update SDK Streaming
**File:** `packages/agent-hub-client/agent_hub/client.py`

- Deprecate `stream()` WebSocket method
- Update `stream_sse()` to be the primary streaming method
- Consider renaming `stream_sse()` to `stream()` after deprecation period

#### 2.4 Update Cancellation Mechanism
**Current:** WebSocket message + REST `/api/sessions/{id}/cancel`
**After:** AbortController + REST `/api/sessions/{id}/cancel`

The REST cancellation endpoint remains - only WebSocket in-band cancel is removed.

#### 2.5 Update Tests
**Files:**
- `backend/tests/api/test_stream.py` - Update to test SSE
- `backend/tests/api/test_stream_cancel.py` - Update cancellation tests
- `packages/agent-hub-client/tests/test_streaming.py` - Update SDK tests

#### 2.6 Update Documentation
**Files:**
- `docs/api-guide.md`
- `docs/feature-parity.md`
- SDK README

#### 2.7 Final Removal (Phase 2)
After deprecation period (e.g., 1 month):
- Remove `/api/stream` endpoint entirely
- Remove `stream_registry.py` (only used for WebSocket tracking)
- Remove WebSocket-specific frontend code
- Remove deprecated SDK method

### Files to Modify (Phase 1 - Deprecation)
- `backend/app/api/stream.py` (add deprecation)
- `frontend/src/hooks/use-chat-stream.ts` (SSE rewrite)
- `frontend/src/lib/api-config.ts` (remove getWsUrl if only used for stream)
- `packages/agent-hub-client/agent_hub/client.py` (deprecate stream())
- Tests and docs

### Files to Remove (Phase 2 - After Deprecation)
- `backend/app/api/stream.py` (entire file)
- `backend/app/services/stream_registry.py` (entire file)
- WebSocket-related tests

---

## Part 3: Enforce agent_slug Across All Endpoints

### Current State

| Endpoint | agent_slug Support |
|----------|-------------------|
| `/api/complete` | FULL - mandates, fallbacks, tracking |
| `/api/stream` | PARTIAL - accepts but ignores (warning logged) |
| `/orchestration/*` | NONE - uses inline SubagentConfig |
| `/api/generate-image` | NONE |
| `/api/sessions` (create) | NONE |
| SDK methods | PARTIAL - only complete() and stream_sse() |

### Solution

#### 3.1 Add agent_slug to Orchestration Endpoints
**File:** `backend/app/api/orchestration.py`

Update request schemas:
```python
class SubagentRequest(BaseModel):
    task: str
    # ... existing fields
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for routing. If provided, loads agent config."
    )
```

Update handlers to resolve agent when agent_slug provided:
```python
if request.agent_slug:
    resolved = await resolve_agent(request.agent_slug, db)
    # Use resolved.model, inject mandates, setup fallbacks
```

Endpoints to update:
- `POST /orchestration/subagent`
- `POST /orchestration/parallel`
- `POST /orchestration/maker-checker`
- `POST /orchestration/code-review`
- `POST /orchestration/roundtable/create`
- `POST /orchestration/run-agent`

#### 3.2 Add agent_slug to Image Generation
**File:** `backend/app/api/image.py`

```python
class ImageGenerationRequest(BaseModel):
    prompt: str
    # ... existing fields
    agent_slug: str | None = Field(default=None, description="Agent slug for image style presets")
```

#### 3.3 Add agent_slug to Session Creation
**File:** `backend/app/api/sessions.py`

```python
class SessionCreate(BaseModel):
    project_id: str
    provider: str
    model: str
    agent_slug: str | None = Field(default=None, description="Agent to use for this session")
```

#### 3.4 Add Response Fields Everywhere
All completion-like endpoints should return:
```python
agent_used: str | None  # Slug of agent that handled request
model_used: str  # Actual model used (may differ from requested if fallback)
fallback_used: bool  # True if primary model failed
```

#### 3.5 Update SDK Client Methods
**File:** `packages/agent-hub-client/agent_hub/client.py`

Add `agent_slug` parameter to:
- `generate_image()`
- `create_session()`
- `run_agent()` (already supports agent execution, add agent_slug for presets)

#### 3.6 Update Frontend Agent Selection
Ensure all pages that make completion calls can select an agent:
- `/chat` - Agent selector dropdown
- `/agents/[slug]/playground` - Already uses agent slug

### Files to Modify
- `backend/app/api/orchestration.py`
- `backend/app/api/image.py`
- `backend/app/api/sessions.py`
- `backend/app/services/orchestration/*.py`
- `packages/agent-hub-client/agent_hub/client.py`
- Frontend pages as needed

---

## Part 4: Complete Frontend Pages

### Current Status

| Page | Status | Action |
|------|--------|--------|
| `/` | Redirect | Keep as-is |
| `/dashboard` | Complete | None |
| `/analytics` | STUB (redirect) | BUILD FULL PAGE |
| `/chat` | Complete | None |
| `/sessions` | Complete | None |
| `/sessions/[id]` | Complete | None |
| `/agents` | Complete | None |
| `/agents/[slug]` | Complete | None |
| `/agents/[slug]/playground` | Complete | None |
| `/agents/[slug]/analytics` | MOCK DATA | CONNECT TO REAL API |
| `/memory` | Complete | None |
| `/settings` | Complete | None |
| `/settings/api-keys` | Complete | None |
| `/settings/preferences` | Complete | None |
| `/admin` | Complete | None |
| `/access-control/*` | Complete | None |

### 4.1 Build /analytics Page
**File:** `frontend/src/app/analytics/page.tsx`

Currently redirects to dashboard. Build dedicated analytics page with:
- Cost breakdown charts (by project, model, day/week/month)
- Token usage trends
- Request volume metrics
- Error rate tracking
- Latency percentiles
- Model comparison
- Filter controls (date range, project, model)

**Backend endpoints to use:**
- `GET /api/analytics/costs`
- `GET /api/analytics/truncations`
- Existing dashboard endpoints

### 4.2 Connect Agent Analytics to Real Data
**File:** `frontend/src/app/agents/[slug]/analytics/page.tsx`

Currently shows: "Analytics data is simulated"

**Backend work needed:**
- Implement `GET /api/agents/{slug}/analytics` endpoint (currently returns placeholder zeros)
- Track per-agent metrics: requests, latency, success rate, token usage, cost

**File:** `backend/app/api/agents.py` (lines 300-357)
```python
# TODO: Replace with actual metrics once agent tracking is implemented
```

Need to:
1. Add agent_id/agent_slug to CostLog model
2. Track agent attribution in completion flow
3. Build aggregation queries for agent metrics
4. Update frontend to use real endpoint

### 4.3 Verify Access Control Sub-pages
These pages were not fully explored but navigation links exist. Verify:
- `/access-control/clients` - Client list
- `/access-control/clients/[id]` - Client detail/management
- `/access-control/clients/new` - New client registration
- `/access-control/requests` - Request log

### Files to Create/Modify
- `frontend/src/app/analytics/page.tsx` (rewrite from redirect)
- `frontend/src/app/agents/[slug]/analytics/page.tsx` (connect to real API)
- `backend/app/api/agents.py` (implement real metrics)
- `backend/app/models.py` (add agent_id to CostLog if needed)

---

## Part 5: SDK Updates

### 5.1 max_tokens Changes
All methods should accept `max_tokens: int | None = None`:
- `complete()` - Done
- `stream()` - Update before deprecation
- `stream_sse()` - Update
- `generate_image()` - N/A (different parameter)
- `run_agent()` - Update

### 5.2 agent_slug Support
Add `agent_slug: str | None = None` to:
- `generate_image()`
- `create_session()`
- `run_agent()`
- `stream()` (before deprecation)

### 5.3 Deprecation Notices
Add deprecation warnings to:
- `stream()` method - Use `stream_sse()` instead

### Files to Modify
- `packages/agent-hub-client/agent_hub/client.py`
- `packages/agent-hub-client/agent_hub/models.py` (if response types need updates)

---

## Part 6: Database/Model Updates

### 6.1 Agent Tracking in Cost Logs
**File:** `backend/app/models.py`

Add to CostLog model:
```python
agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
agent_slug = Column(String(100), nullable=True, index=True)
```

### 6.2 Migration
Create Alembic migration for new columns.

---

## Implementation Order

### Phase 1: Foundation (No Breaking Changes)
1. Remove max_tokens artificial caps (Part 1)
2. Add agent_slug to orchestration endpoints (Part 3.1)
3. Implement agent metrics backend (Part 4.2 backend)

### Phase 2: Frontend Updates
4. Build /analytics page (Part 4.1)
5. Connect agent analytics to real data (Part 4.2)
6. Verify access control pages (Part 4.3)

### Phase 3: Streaming Consolidation
7. Deprecate /api/stream (Part 2.1)
8. Update frontend to SSE (Part 2.2)
9. Update SDK streaming (Part 2.3)
10. Update tests and docs (Part 2.5, 2.6)

### Phase 4: Cleanup
11. Remove deprecated code after deprecation period (Part 2.7)
12. Final verification and testing

---

## Verification Checklist

### Max Tokens Removal
- [ ] Claude adapter uses model max when not specified
- [ ] Gemini adapter doesn't pass max_tokens when not specified
- [ ] API endpoints accept None for max_tokens
- [ ] SDK methods accept None for max_tokens
- [ ] No arbitrary defaults in code (4096, 8192, etc.)
- [ ] Responses not truncated when max_tokens not specified

### Streaming Consolidation
- [ ] Deprecation warning added to /api/stream
- [ ] Frontend works with SSE streaming
- [ ] SDK stream_sse() works correctly
- [ ] Cancellation works via AbortController + REST
- [ ] All tests pass
- [ ] Documentation updated

### agent_slug Enforcement
- [ ] All orchestration endpoints accept agent_slug
- [ ] Image generation accepts agent_slug
- [ ] Session creation accepts agent_slug
- [ ] SDK methods support agent_slug
- [ ] Response includes agent_used, model_used, fallback_used
- [ ] Frontend can select agents where applicable

### Frontend Completion
- [ ] /analytics page fully functional with real data
- [ ] /agents/[slug]/analytics shows real metrics
- [ ] All access-control pages verified working
- [ ] No mock data in production code

### SDK Updates
- [ ] All max_tokens parameters accept None
- [ ] All agent-related methods accept agent_slug
- [ ] Deprecation warnings in place
- [ ] Tests updated

---

## Notes for Future Sessions

This plan covers the major work items. When running `/plan_it` against this file:

1. **Explore further** - Each section may need deeper exploration of specific files
2. **Create subtasks** - Break each Part into specific subtasks with verify_commands
3. **TDD approach** - Write failing tests first, then implement
4. **Incremental deploys** - Deploy and verify each phase before moving to next

The goal is a fully operational Agent Hub with:
- No artificial response truncation
- Single, simple streaming mechanism
- Consistent agent_slug support everywhere
- Complete, functional UI on every page

---

## Reference Documents
- `/home/kasadis/portfolio-ai/tasks/agent-hub-sdk-fix/COMPLETE-FIX-GUIDE.md` - SDK fix patterns
- `/home/kasadis/agent-hub/.index.yaml` - Project index
- `/home/kasadis/agent-hub/plan.json` - Master plan (SOTA integration)
