# Continuation: Model Constants Centralization

**Date:** 2026-01-17
**Context:** Consolidate all LLM model references into PostgreSQL + API architecture
**Status:** Phase 1 complete, Phase 4 ready for execution

## Architecture Decision

**PostgreSQL + API with Smart Client Fallback** - chosen because:
- Instant updates (no redeploys across 7 projects)
- Works for both Python and TypeScript
- Pip client works offline with fallback defaults
- Already have Agent Hub API infrastructure

## Completed

### Phase 1: Database Schema + API ✓
- [x] Created `llm_models` table with migration `e281dbbb5cf4`
- [x] Seeded 6 models (3 Claude, 3 Gemini)
- [x] `GET /api/models` endpoint with provider filter
- [x] `GET /api/models/{id}` endpoint
- [x] `ModelRegistry` service with fallback (`app/services/model_registry.py`)
- [x] 13 new tests, 812 total passing
- [x] Committed: `588cf1d`

---

## Phase 4: Migrate Hardcoded References

### 4.1 agent-hub backend: openai_compat.py

- [ ] Read `backend/app/api/openai_compat.py` to understand current MODEL_MAPPING and AVAILABLE_MODELS
- [ ] Create async helper to load models from database for OpenAI compat endpoint
- [ ] Replace hardcoded `MODEL_MAPPING` dict with database lookup
- [ ] Replace hardcoded `AVAILABLE_MODELS` list with database query
- [ ] Update `/v1/models` endpoint to return data from `llm_models` table
- [ ] Run `dt pytest backend/tests/api/test_openai_compat.py` - verify tests pass
- [ ] Run `dt --check` - verify quality gate passes

### 4.2 agent-hub backend: tier_classifier.py

- [ ] Read `backend/app/services/tier_classifier.py` to understand model tier logic
- [ ] Refactor to use ModelRegistry for model lookups
- [ ] Update any hardcoded model strings to use registry
- [ ] Run tests for tier_classifier if they exist
- [ ] Run `dt --check` - verify quality gate passes

### 4.3 agent-hub backend: token_counter.py

- [ ] Read `backend/app/services/token_counter.py` to find CONTEXT_LIMITS usage
- [ ] Replace hardcoded context limits with `ModelRegistry.get_context_window()`
- [ ] Replace hardcoded output limits with `ModelRegistry.get_max_output_tokens()`
- [ ] Run `dt --check` - verify quality gate passes

### 4.4 agent-hub backend: constants.py cleanup

- [ ] Read `backend/app/constants.py` to inventory all model constants
- [ ] Identify which constants are still needed (OUTPUT_LIMITS, use-case defaults)
- [ ] Add deprecation comments to model string constants pointing to ModelRegistry
- [ ] Grep for usages: `grep -r "from app.constants import.*CLAUDE\|GEMINI" backend/`
- [ ] Update remaining usages to import from ModelRegistry or keep as aliases
- [ ] Run `dt --check` - verify quality gate passes

### 4.5 agent-hub frontend

- [ ] Find model-related hardcoding: `grep -r "claude-\|gemini-" frontend/src/`
- [ ] Create React hook or utility to fetch models from `/api/models`
- [ ] Replace hardcoded model lists in components with API data
- [ ] Test frontend manually - verify model dropdowns work
- [ ] Run `dt --check` - verify quality gate passes

### 4.6 summitflow backend

- [ ] Read `~/summitflow/backend/app/constants.py` to understand current state
- [ ] Option A: Import ModelRegistry from agent-hub-client package
- [ ] Option B: Create local constants that mirror agent-hub (simpler, less coupling)
- [ ] Update any hardcoded model strings
- [ ] Run `dt --check` in summitflow - verify quality gate passes

### 4.7 summitflow frontend

- [ ] Find model hardcoding: `grep -r "claude-\|gemini-" ~/summitflow/frontend/`
- [ ] Update to fetch from agent-hub API or keep as-is if minimal
- [ ] Test frontend manually if changes made

### 4.8 portfolio-ai backend

- [ ] Find model hardcoding: `grep -r "claude-\|gemini-" ~/portfolio-ai/backend/`
- [ ] Update to use constants or ModelRegistry
- [ ] Run `dt --check` in portfolio-ai - verify quality gate passes

### 4.9 agent-hub-client package

- [ ] Read `packages/agent-hub-client/agent_hub/client.py` for current model handling
- [ ] Add ModelRegistry class to package with bundled defaults
- [ ] Export in package `__init__.py`
- [ ] Update package version
- [ ] Run `dt --check` - verify quality gate passes

### 4.10 Final verification

- [ ] Search for legacy models: `grep -rn "gemini-2\.\|claude-3-" ~/agent-hub ~/summitflow ~/portfolio-ai`
- [ ] Verify returns nothing (all legacy references removed)
- [ ] Run `dt --check` on all projects
- [ ] Commit all changes: `/commit_it`

---

## Phase 5: CI Model Discovery (DEFERRED)

Future work - create SummitFlow task when Phase 4 complete:
- GitHub Action cron job (daily)
- Call Anthropic `GET /v1/models` API
- Call Google Vertex AI model list API
- Compare to database, alert on new/missing models

---

## Quick Reference

```bash
# Verify Phase 1 infrastructure
curl http://localhost:8003/api/models | jq
curl http://localhost:8003/api/models/claude-sonnet-4-5 | jq

# Search for hardcoded models
grep -rn "claude-sonnet-4-5\|claude-opus-4-5\|gemini-3-" backend/

# Run quality gate
dt --check

# Commit when ready
/commit_it
```

## Files from Phase 1

- `backend/app/models.py` - LLMModel SQLAlchemy model
- `backend/app/api/models.py` - API endpoints
- `backend/app/services/model_registry.py` - ModelRegistry service
- `backend/migrations/versions/e281dbbb5cf4_add_llm_models_table.py` - Migration
