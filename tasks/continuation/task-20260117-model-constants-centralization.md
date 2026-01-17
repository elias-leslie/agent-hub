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

### Completed This Session
- [x] Fixed legacy `gemini-2.0-flash-preview-image-generation` → `gemini-3-pro-image-preview`
- [x] Added `GEMINI_IMAGE` constant to `app/constants.py`
- [x] Updated `gemini_image.py` to use constant
- [x] Updated `app/api/image.py` to use constant
- [x] Updated `tests/api/test_image.py` to use constant
- [x] Updated `agent-hub-client` package (2 places)
- [x] Created SummitFlow task for voice interruption architecture (task-82292e11)
- [x] Fixed 7 test failures + 18 lint violations from previous session

## Implementation Plan

### Phase 1: Database Schema + API (Day 1-2)

```sql
CREATE TABLE llm_models (
    id TEXT PRIMARY KEY,              -- 'claude-sonnet-4-5'
    display_name TEXT NOT NULL,       -- 'Claude Sonnet 4.5'
    provider TEXT NOT NULL,           -- 'anthropic', 'google'
    family TEXT,                      -- 'claude-4', 'gemini-3'
    context_window INTEGER NOT NULL,
    max_output_tokens INTEGER,
    input_price_per_m DECIMAL,
    output_price_per_m DECIMAL,
    capabilities JSONB,               -- {"vision": true, "image_gen": true, "function_calling": true}
    is_deprecated BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,   -- Kill switch
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed data
INSERT INTO llm_models (id, display_name, provider, family, context_window, max_output_tokens, capabilities, is_active) VALUES
('claude-sonnet-4-5', 'Claude Sonnet 4.5', 'anthropic', 'claude-4', 200000, 64000, '{"vision": true, "function_calling": true}', true),
('claude-opus-4-5', 'Claude Opus 4.5', 'anthropic', 'claude-4', 200000, 64000, '{"vision": true, "function_calling": true}', true),
('claude-haiku-4-5', 'Claude Haiku 4.5', 'anthropic', 'claude-4', 200000, 64000, '{"vision": true, "function_calling": true}', true),
('gemini-3-flash-preview', 'Gemini 3 Flash', 'google', 'gemini-3', 1000000, 65536, '{"vision": true, "function_calling": true}', true),
('gemini-3-pro-preview', 'Gemini 3 Pro', 'google', 'gemini-3', 1000000, 65536, '{"vision": true, "function_calling": true}', true),
('gemini-3-pro-image-preview', 'Gemini 3 Pro Image', 'google', 'gemini-3', 1000000, 65536, '{"vision": true, "image_gen": true}', true);
```

### Phase 2: API Endpoint (Day 2)

Add to Agent Hub:
- `GET /api/v1/models` - List all active models
- `GET /api/v1/models/{id}` - Get specific model details
- Response includes all metadata (context window, pricing, capabilities)

### Phase 3: Python ModelRegistry (Day 3)

Create shared utility with smart fallback:

```python
# app/services/model_registry.py
class ModelRegistry:
    _instance = None
    _models: dict[str, ModelInfo] = {}
    _defaults_loaded = False

    def __init__(self):
        self._load_defaults()  # From bundled defaults.json

    async def refresh(self, timeout: float = 2.0):
        """Fetch latest from API, fall back to defaults on failure."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{AGENT_HUB_URL}/api/v1/models")
                self._models = {m["id"]: ModelInfo(**m) for m in resp.json()}
        except Exception:
            logger.warning("Using cached model defaults")

    def get(self, model_id: str) -> ModelInfo | None:
        return self._models.get(model_id)

    def list_by_provider(self, provider: str) -> list[ModelInfo]:
        return [m for m in self._models.values() if m.provider == provider]
```

### Phase 4: Migrate All Hardcoded References (Day 4)

**Files to update in agent-hub:**
- `app/constants.py` → Keep as aliases to registry or remove
- `app/api/openai_compat.py` → Use registry
- `app/api/preferences.py` → Use registry
- `app/services/tier_classifier.py` → Use registry
- `frontend/src/hooks/use-chat-stream.ts` → Fetch from API
- All other hardcoded model strings

**Files to update in summitflow:**
- `backend/app/constants.py` → Import from agent-hub or use registry
- `backend/app/services/*.py` → Use registry
- `frontend/components/*.tsx` → Fetch from API

**Files to update in portfolio-ai:**
- `backend/app/agents/*.py` → Use registry

### Phase 5: CI Cron Job for Model Discovery (Day 5)

GitHub Action that runs daily:
1. Calls Anthropic `GET /v1/models` API
2. Calls Google Vertex AI model list API
3. Compares to database
4. If new model found → Slack alert + optional auto-insert
5. If configured model missing → P0 alert

## Known Issues / Risks

1. **Pip client offline mode** - Must bundle `defaults.json` with package
2. **TypeScript type safety** - Lose strict typing, use runtime validation
3. **Migration complexity** - 7 projects, need coordinated rollout
4. **API dependency** - Frontends need API up to get model list

## Files Modified This Session

- `backend/app/constants.py` - Added GEMINI_IMAGE
- `backend/app/adapters/gemini_image.py` - Use GEMINI_IMAGE constant
- `backend/app/api/image.py` - Use GEMINI_IMAGE constant
- `backend/tests/api/test_image.py` - Use GEMINI_IMAGE constant
- `packages/agent-hub-client/agent_hub/client.py` - Updated model string (2 places)

## Resume Instructions

```bash
# Check current state
cd ~/agent-hub
git status
dt --check

# Start implementation
# 1. Create migration for llm_models table
cd backend
alembic revision --autogenerate -m "Add llm_models table"

# 2. Add API endpoint
# Edit app/api/models.py (new file)

# 3. Create ModelRegistry service
# Edit app/services/model_registry.py (new file)
```

## Acceptance Criteria

- [ ] `llm_models` table created with seed data
- [ ] `GET /api/v1/models` endpoint working
- [ ] ModelRegistry class with fallback implemented
- [ ] All hardcoded model strings in agent-hub removed
- [ ] All hardcoded model strings in summitflow removed
- [ ] All hardcoded model strings in portfolio-ai removed
- [ ] TypeScript frontends fetch from API
- [ ] CI cron job detecting new models
- [ ] `dt --check` passes on all projects
- [ ] No `gemini-2.*` or `claude-3-*` references anywhere

## References

- Gemini Pro architecture recommendation (this session)
- Anthropic Models API: `GET https://api.anthropic.com/v1/models`
- Google Vertex AI Model Garden API
- [Nano Banana docs](https://ai.google.dev/gemini-api/docs/image-generation)
