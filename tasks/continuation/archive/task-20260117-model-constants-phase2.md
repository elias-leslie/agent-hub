# Continuation: Model Constants - Cross-Project Cleanup

**Date:** 2026-01-17
**Context:** Complete model constants migration across all projects
**Status:** Phase 1 complete (agent-hub), Phase 2 pending (other projects)

## Completed

### agent-hub (DONE)
- [x] Deleted over-engineered database infrastructure (llm_models table, ModelRegistry HTTP-to-self)
- [x] Cleaned up constants.py - removed `_FULL` variants, added `resolve_model()` function
- [x] Updated openai_compat.py to use constants
- [x] Updated tier_classifier.py, router.py, roundtable.py, subagent.py
- [x] Fixed all tests to use constants
- [x] agent-hub-client package exports constants
- [x] All 787 tests passing, committed: 878edff

---

## Remaining Work

### Phase 2.1: summitflow backend

Pre-existing type errors block commit (unrelated to model constants):
```
app/api/checkpoints.py: 3 mypy errors (no-any-return)
```

Model constants work:
- [ ] Check `~/summitflow/backend/app/constants.py` for model references
- [ ] Search: `grep -rn "claude-\|gemini-" ~/summitflow/backend/`
- [ ] Update any hardcoded model strings to use agent-hub-client constants
- [ ] Decide: import from agent-hub-client OR duplicate constants locally

### Phase 2.2: summitflow frontend
- [ ] Search: `grep -rn "claude-\|gemini-" ~/summitflow/frontend/`
- [ ] If model strings found, update to fetch from agent-hub API or use constants

### Phase 2.3: portfolio-ai backend
- [ ] Search: `grep -rn "claude-\|gemini-" ~/portfolio-ai/backend/`
- [ ] Update any hardcoded model strings

### Phase 2.4: portfolio-ai frontend
- [ ] Search: `grep -rn "claude-\|gemini-" ~/portfolio-ai/frontend/`
- [ ] Update if needed

### Phase 2.5: Final verification
- [ ] `grep -rn "gemini-2\.\|claude-3-" ~/agent-hub ~/summitflow ~/portfolio-ai` returns nothing
- [ ] All projects pass `dt --check`
- [ ] Commit all changes

---

## Key Files Reference

**Source of truth:**
- `agent-hub/backend/app/constants.py` - canonical constants
- `agent-hub/packages/agent-hub-client/agent_hub/constants.py` - pip-installable version

**Functions available:**
```python
from app.constants import (
    CLAUDE_SONNET, CLAUDE_OPUS, CLAUDE_HAIKU,
    GEMINI_FLASH, GEMINI_PRO,
    resolve_model,  # alias -> canonical ID
    MODEL_ALIASES,  # {"sonnet": "claude-sonnet-4-5", ...}
)
```

**From agent-hub-client:**
```python
from agent_hub import CLAUDE_SONNET, GEMINI_FLASH
```

---

## Resume Command

```
/do_it tasks/continuation/task-20260117-model-constants-phase2.md
```
