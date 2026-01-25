# Task: Memory System Terminology & Tier Alignment

## Objective
Achieve complete alignment of memory system terminology, categorization, and injection tier assignment across ALL layers (database, backend, frontend, hooks, documentation, memory content itself).

## Problem Statement
The memory system has evolved organically and now has misaligned terminology, multiple categorization schemes, and fragile keyword-based tier assignment. This creates confusion and technical debt.

---

## Issues to Address

### Issue 1: Fragile Tier Assignment
**Current state:** 3-block injection system uses keyword matching at retrieval time
- Mandates: `source_description` contains `'golden_standard'` OR `'confidence:100'`
- Guardrails: Semantic search + keyword filter (`gotcha`, `pitfall`, `warning`, etc.)
- Reference: Semantic search excluding warning keywords

**Problem:** Keyword matching is fragile, will break at scale, and is non-deterministic.

### Issue 2: Multiple Categorization Schemes
**Scheme 1 - EpisodeType enum (types.py):** MANDATE, GUARDRAIL, PATTERN, DISCOVERY, GOTCHA, SESSION, TASK
- Status: UNUSED - never wired into injection system

**Scheme 2 - DB categories (save-learning API):** coding_standard, troubleshooting_guide, operational_context, system_design, domain_knowledge
- Status: Used for storage, not aligned with injection

**Scheme 3 - 3-block injection:** mandates, guardrails, reference
- Status: Used for output, keyword-assigned

**Problem:** Three schemes don't align. Confusing for users and maintainers.

### Issue 3: Inconsistent Terminology Across Layers

| Layer | Terms Used |
|-------|------------|
| InjectionTier enum | ALWAYS, HIGH, MEDIUM, LOW, NEVER |
| 3-block API response | mandates, guardrails, reference |
| Module name | golden_standards.py |
| API endpoint | /api/memory/golden-standards |
| Hook output | "Mandates:", "Guardrails:", "Reference:" |
| UI labels | "Mandates", "Guardrails", "Reference" |
| Memory content | References "golden-standards API", "mandates", etc. |
| CLAUDE.md docs | References "mandates", "golden standards" |

**Problem:** Mixed terminology creates confusion. No single source of truth for naming.

### Issue 4: 144 Episodes Need Tier Assignment
**Current state:** Episodes don't have explicit tier field. Tier is guessed at retrieval time.

**Problem:** Need to review and assign proper tiers to all existing episodes.

### Issue 5: Consulted Recommendation Not Fully Integrated
**Gemini Pro recommended CCP taxonomy:**
- `constraint` - Rules, must/must-not (prescriptive)
- `context` - Facts about system/environment (descriptive)
- `pattern` - Heuristics, gotchas, solutions (corrective)

**Problem:** This recommendation needs to be evaluated against all layers and integrated consistently.

---

## Affected Areas (Inventory)

### Backend Code
- `backend/app/services/memory/types.py` - EpisodeType enum, InjectionTier enum
- `backend/app/services/memory/context_injector.py` - get_mandates(), get_guardrails(), get_reference()
- `backend/app/services/memory/golden_standards.py` - Module name, functions
- `backend/app/services/memory/episode_creator.py` - Episode creation
- `backend/app/services/memory/ingestion_config.py` - Ingestion profiles
- `backend/app/api/memory.py` - API endpoints, schemas, category enum

### Frontend Code
- `frontend/src/components/memory/*` - UI components, labels
- `frontend/src/lib/api/memory-settings.ts` - API types

### Hooks & Scripts
- `~/.claude/hooks/graphiti-client.sh` - Output formatting
- `~/.claude/hooks/SessionStart.sh` - Memory injection

### Database/Graphiti
- Episode nodes - Need injection_tier field
- Episode content - Some reference old terminology
- 144 existing episodes - Need manual review and tier assignment

### Documentation
- `~/.claude/CLAUDE.md` - Global instructions
- Project CLAUDE.md files - Project instructions
- Memory content itself - Some memories describe the old API/terminology

---

## Constraints
- Follow global claude.md rules (simplicity, no over-engineering)
- Changes may be breaking - need migration strategy
- 144 episodes require FULL MANUAL REVIEW (no keyword automation)
- Must maintain functionality during transition

---

## Next Session Protocol

1. **Run /plan_it** against this task file
2. **Interview** using AskUserQuestion sequentially (one question informs the next)
3. **Consult /consult --pro** for architectural decisions
4. **Explore thoroughly** using explore agents to find all affected files/code
5. **Propose unified terminology** before implementing
6. **Create migration strategy** for breaking changes

---

## Final Verification Checklist (End of Implementation)

Use this checklist at the end of implementation. Spawn explore agents to verify each item.

### Terminology Alignment
- [ ] No references to "golden_standard" in code (except migration)
- [ ] No references to old 5 categories in code
- [ ] API responses use consistent terminology
- [ ] UI labels match API terminology
- [ ] Hook output matches API terminology
- [ ] CLAUDE.md files updated

### Tier Assignment
- [ ] All 144 episodes have explicit injection_tier field
- [ ] Retrieval uses field lookup, not keyword matching
- [ ] No keyword matching logic remains in context_injector.py

### Category Consolidation
- [ ] Single category taxonomy in use
- [ ] Old categories migrated
- [ ] save-learning API uses new categories
- [ ] UI category dropdowns updated

### Functional Tests
- [ ] Memory injection still works
- [ ] Budget enforcement still works
- [ ] All memory tests pass
- [ ] Hook produces correct output format

### Content Review
- [ ] Memory content referencing old APIs/terms identified
- [ ] Decision made on whether to update memory content

---

## Session 1 Decisions (Already Made)

These decisions were made in the previous session after consulting Gemini Pro:

1. **Backfill approach:** Manual review of ALL 144 episodes (no keyword automation)
2. **EpisodeType enum:** Remove (unused)
3. **Category taxonomy:** CCP recommended (constraint/context/pattern) - needs final confirmation
4. **Scoring system:** Unchanged - ranks within tiers, orthogonal to tier assignment
