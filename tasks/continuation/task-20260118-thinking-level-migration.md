---
created: 2026-01-18T12:42:00
status: in_progress
context_pct: 75
files_modified:
  - backend/app/adapters/claude.py
  - backend/app/adapters/gemini.py
  - backend/app/api/complete.py
  - backend/app/api/orchestration.py
  - backend/app/services/completion.py
  - backend/app/services/agent_runner.py
  - backend/app/services/orchestration/subagent.py
  - backend/app/services/orchestration/parallel.py
---

# Thinking Level Migration: budget_tokens → thinking_level

## Summary

Migrated from provider-specific `budget_tokens` to provider-agnostic `thinking_level` parameter.

## Completed Work

- [x] Research Gemini 3 thinking configuration (uses `thinking_level`, NOT `thinking_budget`)
- [x] Research Claude API (still uses `budget_tokens` internally, wrapped in `thinking` object)
- [x] Update Gemini adapter to use `thinking_level` parameter
- [x] Update Claude adapter with `_get_claude_thinking_budget()` to map levels to tokens
- [x] Add `thinking_level` parameter to API schemas (complete.py, orchestration.py)
- [x] Remove deprecated trigger detection (ultrathink keywords in prompts don't work anymore)
- [x] Update all services (completion.py, agent_runner.py, orchestration services)
- [x] Quality checks pass (lint, types)

## Remaining Work (P1 - Must Fix)

- [ ] Update test_subagent.py tests to use `thinking_level` instead of `budget_tokens`
- [ ] Update test_extended.py tests to use `thinking_level` instead of `budget_tokens`
- [ ] Run full test suite to verify all 800 tests pass
- [ ] Use `/claude_it` to capture learnings about:
  - Gemini 3 thinking_level configuration
  - Ultrathink keyword deprecation
  - Stale version search anti-pattern

## Test Failures to Fix

```
FAILED tests/orchestration/test_subagent.py::TestSubagentConfig::test_default_values
  - Change: assert config.budget_tokens → assert config.thinking_level

FAILED tests/orchestration/test_subagent.py::TestSubagentConfig::test_custom_values
  - Change: budget_tokens=1000 → thinking_level="low"

FAILED tests/thinking/test_extended.py::TestExtendedThinking::test_thinking_with_budget_tokens
  - Test name should change to test_thinking_with_thinking_level
  - Update to pass thinking_level instead of budget_tokens

FAILED tests/thinking/test_extended.py::TestExtendedThinking::test_thinking_with_tools_uses_beta_api
  - Mock issue, may need to update how thinking is passed

FAILED tests/thinking/test_extended.py::TestExtendedThinking::test_thinking_forces_temperature_one
  - Update to use thinking_level="high" instead of budget_tokens
```

## API Changes

| Old | New |
|-----|-----|
| `budget_tokens: int` | `thinking_level: str` |
| `budget_tokens=16000` | `thinking_level="high"` |

### Thinking Level Values

| Level | Claude Budget | Gemini 3 Pro | Gemini 3 Flash |
|-------|---------------|--------------|----------------|
| minimal | None | N/A | "minimal" |
| low | 1024 | "low" | "low" |
| medium | 4096 | "high" | "medium" |
| high | 16384 | "high" | "high" |
| ultrathink | 65536 | "high" | "high" |

## Key Learnings (Capture with /claude_it)

1. **Gemini 3 uses thinking_level, not thinking_budget**
   - Deprecated: `ThinkingConfig(thinking_budget=N)`
   - Correct: `ThinkingConfig(thinking_level="low"|"high")`

2. **Ultrathink keywords are deprecated in Claude Code**
   - Keywords in prompt text ("ultrathink", "think hard") no longer auto-enable thinking
   - Only explicit `thinking_level` parameter works

3. **Don't search with stale version numbers**
   - Training data is outdated
   - Search general terms first, let results reveal current versions

## Resume Instructions

```bash
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260118-thinking-level-migration.md
```

## Files to Update

1. `backend/tests/orchestration/test_subagent.py` - Update SubagentConfig tests
2. `backend/tests/thinking/test_extended.py` - Update extended thinking tests
