# Continuation: Model Constants Centralization

**Date:** 2026-01-17
**Context:** Consolidate all LLM model references into PostgreSQL + API architecture
**Previous Session:** Fixed legacy gemini-2.0 image model, researched architecture with Gemini Pro

## Decision Made

**Architecture: PostgreSQL + API with Smart Client Fallback**

Gemini Pro recommended this over shared Python package or codegen because:
- Instant updates (no redeploys across 7 projects)
- Works for both Python and TypeScript
- Pip client works offline with fallback defaults
- Already have Agent Hub API infrastructure

## Scope

### Projects Needing Migration

| Project | Language | Current State | References |
|---------|----------|---------------|------------|
| agent-hub backend | Python | Has `constants.py` | 132 |
| agent-hub frontend | TypeScript | Hardcoded | ~20 |
| agent-hub-client | Python (pip) | Hardcoded | 2 |
| summitflow backend | Python | Has `constants.py` | 72 |
| summitflow frontend | TypeScript | Hardcoded | ~10 |
| portfolio-ai backend | Python | Hardcoded | 7 |
| terminal frontend | TypeScript | Hardcoded | 1 |

## Completed

### Previous Session
- [x] Fixed legacy `gemini-2.0-flash-preview-image-generation` → `gemini-3-pro-image-preview`
- [x] Added `GEMINI_IMAGE` constant to `app/constants.py`
- [x] Updated `gemini_image.py` to use constant
- [x] Updated `app/api/image.py` to use constant
- [x] Updated `tests/api/test_image.py` to use constant
- [x] Updated `agent-hub-client` package (2 places)
- [x] Created SummitFlow task for voice interruption architecture (task-82292e11)
- [x] Fixed 7 test failures + 18 lint violations from previous session

### Phase 1: Database Schema + API (COMPLETE)
- [x] Created alembic migration `e281dbbb5cf4_add_llm_models_table.py`
- [x] `llm_models` table with seed data (6 models: 3 Claude, 3 Gemini)
- [x] `GET /api/models` endpoint - list models with provider filter
- [x] `GET /api/models/{id}` endpoint - get single model details
- [x] ModelRegistry service with smart fallback (`app/services/model_registry.py`)
- [x] Tests: 13 new tests for models API + ModelRegistry (812 total tests passing)
- [x] Quality gate: `dt --check` passes

## Remaining Work

### Phase 4: Migrate Hardcoded References (Next Session)

**agent-hub backend:**
- [ ] `app/api/openai_compat.py` - Replace `MODEL_MAPPING` and `AVAILABLE_MODELS` with registry
- [ ] `app/api/preferences.py` - Use registry for model validation
- [ ] `app/services/tier_classifier.py` - Use registry for tier mapping
- [ ] `app/services/token_counter.py` - Use registry for context limits
- [ ] `app/constants.py` - Deprecate/remove hardcoded constants

**agent-hub frontend:**
- [ ] Fetch model list from `/api/models` instead of hardcoding

**summitflow:**
- [ ] `backend/app/constants.py` - Use registry or import from agent-hub
- [ ] `frontend/components/*.tsx` - Fetch from API

**portfolio-ai:**
- [ ] `backend/app/agents/*.py` - Use registry

**agent-hub-client:**
- [ ] Add ModelRegistry to pip package with bundled defaults

### Phase 5: CI Cron Job (Future)
- [ ] GitHub Action for model discovery
- [ ] Anthropic/Google API comparison
- [ ] Slack alerting for new models

## Files Created This Session

- `backend/migrations/versions/8939a1bd7848_merge_heads.py` - Alembic merge
- `backend/migrations/versions/e281dbbb5cf4_add_llm_models_table.py` - LLM models schema + seed
- `backend/app/models.py` - Added `LLMModel` class
- `backend/app/api/models.py` - Models API endpoints
- `backend/app/services/model_registry.py` - ModelRegistry service
- `backend/tests/api/test_models.py` - API tests
- `backend/tests/services/test_model_registry.py` - Service tests

## Resume Instructions

```bash
# Check current state
cd ~/agent-hub
git status
dt --check

# Verify API works
curl http://localhost:8003/api/models | jq

# Next: Migrate openai_compat.py to use ModelRegistry
# Replace MODEL_MAPPING and AVAILABLE_MODELS with database-backed data
```

## Acceptance Criteria

- [x] `llm_models` table created with seed data
- [x] `GET /api/models` endpoint working
- [x] ModelRegistry class with fallback implemented
- [ ] All hardcoded model strings in agent-hub removed
- [ ] All hardcoded model strings in summitflow removed
- [ ] All hardcoded model strings in portfolio-ai removed
- [ ] TypeScript frontends fetch from API
- [ ] CI cron job detecting new models
- [x] `dt --check` passes on agent-hub
- [ ] No `gemini-2.*` or `claude-3-*` references anywhere

## References

- Gemini Pro architecture recommendation (this session)
- Anthropic Models API: `GET https://api.anthropic.com/v1/models`
- Google Vertex AI Model Garden API
- [Nano Banana docs](https://ai.google.dev/gemini-api/docs/image-generation)
