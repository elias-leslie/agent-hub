# Johnny Enhancement Plan (Revised)

**Date:** 2026-02-05
**Status:** Tasks created, ready to execute

## Key Decisions

1. **Rename deferred** - All memory→johnny renaming is optional/later
2. **Extend, don't replace** - Build on existing /api/memory/* endpoints
3. **Agent-agnostic** - Memory system works for all providers, not just Claude
4. **Johnny plugin = separate** - Observation capture plugin separate from enforcement hooks
5. **Privacy built into capture** - <private> tag filtering in observation endpoint
6. **Dashboard tabs on /memory page** - URL params, not sub-routes

## Task Priority Order (10 tasks)

| # | Task | Blocked By | Effort |
|---|------|-----------|--------|
| 24 | Wire task_type/phase into completion flow | - | Small (~3 files) |
| 25 | Add observation capture endpoint + privacy filtering | 24 | Medium |
| 26 | Fix Johnny plugin → /api/memory/* | 25 | Small |
| 27 | Add tab navigation to /memory dashboard | 24 | Medium |
| 28 | Timeline tab | 27 | Medium |
| 29 | Sessions tab | 27 | Medium |
| 30 | Capture tab (SSE) | 25, 27 | Large |
| 31 | Analytics tab | 27 | Medium |
| 32 | Session summary auto-generation | 29 | Large |
| 33 | Cross-session continuity injection | 32 | Medium |

## Dependency Graph

```
#24 Wire task_type/phase ← START
 ├── #25 Observation capture + privacy
 │    ├── #26 Fix Johnny plugin
 │    └── #30 Capture tab (also needs #27)
 └── #27 Tab navigation
      ├── #28 Timeline tab
      ├── #29 Sessions tab → #32 Session summary → #33 Continuity
      ├── #30 Capture tab (also needs #25)
      └── #31 Analytics tab
```

## What Already Exists (DO NOT REPLACE)

### Backend (60+ files at backend/app/services/memory/)
- MemoryService, Graphiti client, episode CRUD
- Progressive context injection (mandates/guardrails/reference)
- Usage tracking (loaded/referenced/helpful/harmful)
- Citation parsing, tier optimizer, learning extractor
- A/B testing framework, TOON reference index

### API (9 modules at backend/app/api/memory*.py)
- Full CRUD, search, bulk ops, settings, metrics
- Agent tools: save-learning, extract-learnings, progressive-context
- Triggered references by task_type and phase (endpoints exist)
- Episode rating (helpful/harmful/used)

### Frontend (20+ components)
- /memory page with table/list views
- Filters, sorting, bulk actions, settings modal
- Stats cards, category/scope pills

### Hooks (at ~/.claude/hooks/)
- SessionStart.sh - injects memory via graphiti-client.sh
- PostToolUse.sh - commit checkpoints, workflow tracking
- PreToolUse.sh - blocks destructive commands

### Johnny Plugin (at ~/.claude/plugins/johnny/) - NEEDS FIX
- Calls /api/johnny/* (doesn't exist) → should be /api/memory/*
- Has session-start.sh, post-tool-use.sh, stop.sh hooks

## Wiring Gap Found

`build_progressive_context()` accepts task_type parameter but completion
endpoints NEVER pass it. Phase-triggered references NOT called during
progressive context building. Fix = Task #24.
