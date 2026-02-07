# Plan: Fix Autonomous Execution Pipeline + Prompt System + Memory Curation

## Context

End-to-end test of autonomous pipeline revealed 4 systemic issues. Through discussion, Fixes 2-3 evolved into larger architectural improvements: a **Prompt Management System** and **Per-Agent Memory Curation**.

## Overview

| # | Fix | Scope | Project(s) |
|---|-----|-------|------------|
| 1 | Worktree node_modules symlink | Quick fix | summitflow |
| 2 | Prompt Management System | New feature | agent-hub + summitflow |
| 3 | Per-Agent Memory Curation | New feature | agent-hub |

---

## Fix 1: Worktree Missing node_modules → TSC Fails

**Problem**: `git worktree add` doesn't include gitignored dirs. `dt --check` detects `has_frontend()=true` and runs `npx tsc --noEmit` which fails → blocks ALL worktree tasks.

**Fix**: Symlink `frontend/node_modules` from main repo into worktree during creation.

**File**: `summitflow/backend/cli/lib/worktree.py` — `create_worktree()` (~line 206, after successful git worktree add)

```python
main_repo = _get_repo_root()
wt_path = Path(worktree_path)

main_node_modules = main_repo / "frontend" / "node_modules"
wt_frontend = wt_path / "frontend"
if main_node_modules.exists() and wt_frontend.exists():
    wt_node_modules = wt_frontend / "node_modules"
    if not wt_node_modules.exists():
        wt_node_modules.symlink_to(main_node_modules)
```

**Why symlink not install**: Instant, shares deps (worktree tracks main), consistent with how `dt` handles venvs.

---

## Fix 2: Prompt Management System

### Problem

13 hardcoded prompts across both projects. Not editable without code changes. Summitflow agents waste turns on irrelevant instructions baked into f-strings.

### Inventory of All 13 Hardcoded Prompts

| # | File | Project | Purpose |
|---|------|---------|---------|
| 1 | `services/memory/summary_generator.py` | agent-hub | Session summarization |
| 2 | `mcp_server.py` | agent-hub | MCP system instruction |
| 3 | `services/memory/learning_extractor.py` | agent-hub | Learning extraction from transcripts |
| 4 | `tasks/autonomous/execution.py` (pristine_self_heal) | summitflow | Quality gate fix prompt |
| 5 | `tasks/autonomous/execution.py` (_build_subtask_prompt) | summitflow | Subtask execution framing |
| 6 | `tasks/autonomous/execution.py` (_build_fix_prompt) | summitflow | Verification failure fix prompt |
| 7 | `tasks/autonomous/escalation.py` (sync) | summitflow | Supervisor guidance |
| 8 | `tasks/autonomous/escalation.py` (async) | summitflow | Supervisor guidance (async) |
| 9 | `tasks/autonomous/review.py` | summitflow | AI code review |
| 10 | `tasks/autonomous/planning.py` | summitflow | Implementation planning (100 lines) |
| 11 | `tasks/autonomous/triage.py` | summitflow | Idea assessment |
| 12 | `tasks/ai_review_quality.py` (user prompt) | summitflow | UI design review |
| 13 | `tasks/ai_review_quality.py` (system prompt) | summitflow | UI reviewer system |

### Architecture

**DB Schema:**

```sql
CREATE TABLE prompts (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    description TEXT,
    is_global BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE agent_prompts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    role VARCHAR(100) NOT NULL,
    priority INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(agent_id, prompt_id)
);

CREATE INDEX idx_agent_prompts_agent_id ON agent_prompts(agent_id);
CREATE INDEX idx_agent_prompts_role ON agent_prompts(role);
CREATE INDEX idx_prompts_is_global ON prompts(is_global) WHERE is_global = TRUE;
```

**Roles** are free-text strings on the join table. No separate table. UI shows dropdown of existing roles + free text entry. Initial roles seeded:
- `execution_rules` — autonomous coding rules (don't use st CLI, etc.)
- `self_heal_rules` — quality gate fix instructions
- `planning_rules` — implementation planning instructions
- `review_criteria` — code review criteria
- `triage_criteria` — idea assessment criteria
- `supervisor_guidance` — escalation guidance format
- `ui_review_criteria` — UI/frontend review criteria

**Composition Order** (system message built by Agent Hub completion service):
1. Global prompts (`is_global=true`) — foundational rules
2. Agent persona (`system_prompt` field on Agent) — agent identity
3. Role-assigned prompts in priority order — specific instructions
4. Memory episodes — mandates, guardrails, references
5. [User message = dynamic task data from summitflow]

**Agent Hub assembles everything.** Summitflow sends only dynamic parts (objective, steps, verification commands, error output) as the user message.

### Backend Changes (agent-hub)

#### New Model: `backend/app/models/prompt.py`

```python
class Prompt(Base):
    __tablename__ = "prompts"
    id, slug, name, content, description, is_global, created_at, updated_at

class AgentPrompt(Base):
    __tablename__ = "agent_prompts"
    id, agent_id (FK agents.id), prompt_id (FK prompts.id), role, priority, created_at
```

#### New API: `backend/app/api/prompts.py`

CRUD endpoints:
- `GET /api/prompts` — list all prompts (with optional `is_global` filter)
- `POST /api/prompts` — create prompt
- `GET /api/prompts/{slug}` — get prompt by slug
- `PUT /api/prompts/{slug}` — update prompt
- `DELETE /api/prompts/{slug}` — delete prompt (cascade removes assignments)
- `GET /api/prompts/roles` — list distinct roles (for dropdown)

Assignment endpoints:
- `GET /api/agents/{slug}/prompts` — list agent's assigned prompts
- `POST /api/agents/{slug}/prompts` — assign prompt to agent (with role + priority)
- `DELETE /api/agents/{slug}/prompts/{prompt_slug}` — remove assignment
- `PUT /api/agents/{slug}/prompts/{prompt_slug}` — update role/priority

#### Modify: `backend/app/services/agent_routing.py`

`inject_agent_mandates()` currently builds system content from:
1. Platform context (global instructions)
2. Agent persona (`system_prompt`)

Change to:
1. Global prompts (from DB, `is_global=true`)
2. Agent persona (`system_prompt`)
3. Agent's role-assigned prompts (from `agent_prompts` join, ordered by priority)
4. Memory episodes (existing injection)

#### New Service: `backend/app/services/prompt_service.py`

- `get_global_prompts()` — fetch all `is_global=true` prompts
- `get_agent_prompts(agent_id)` — fetch agent's assigned prompts ordered by priority
- `build_prompt_context(agent_id)` — compose global + role prompts into system content
- CRUD operations for prompts and assignments

### Frontend Changes (agent-hub)

#### New Page: Prompts Management

- `/prompts` — list all prompts with search/filter by role, global status
- `/prompts/new` — create prompt form (slug, name, content with markdown editor, description, is_global toggle)
- `/prompts/{slug}` — edit prompt
- Add to NAV_ITEMS in app-shell.tsx

#### Agent Editor: Prompts Tab

New tab in agent editor (`/agents/{slug}`):
- List of assigned prompts with role and priority
- "Assign Prompt" button → modal with prompt selector + role dropdown + priority
- Drag to reorder (updates priority)
- Remove assignment button
- Preview: shows composed prompt context (global + persona + role prompts)

### Summitflow Changes

Strip hardcoded instructions from all prompt builders. Keep only dynamic data framing.

#### `execution.py` — `_build_subtask_prompt()`
- Remove: all static instruction text
- Keep: objective, steps with verify_command/expected_output, execution context (task_id, subtask_id, project_path)
- The `execution_rules` prompt (assigned to the agent) handles "don't use st CLI", "focus only on code"

#### `execution.py` — `_build_fix_prompt()`
- Remove: "Do NOT create tasks..." and similar static rules
- Keep: failed step details, verification output, supervisor guidance injection

#### `execution.py` — `pristine_self_heal()`
- Remove: static rules ("only edit source files", "do NOT run st/git")
- Keep: error output, dynamic framing

#### `escalation.py` — supervisor guidance prompts
- Remove: static instruction text
- Keep: task_id, subtask_id, issue_description, step_context

#### `review.py` — AI review prompt
- Remove: review criteria, verdict format instructions
- Keep: task title, complexity, git_diff

#### `planning.py` — planning prompt
- Remove: 100 lines of planning instructions (verify command patterns, constraints)
- Keep: title, description

#### `triage.py` — idea triage prompt
- Remove: assessment criteria, output format
- Keep: title, description

#### `ai_review_quality.py` — UI review
- Remove: review criteria, system prompt text
- Keep: task title, description

### Seed Data

Migration seeds the `prompts` table with content extracted from the 13 hardcoded locations:

| Slug | Role | is_global | Source |
|------|------|-----------|--------|
| `global-instructions` | — | true | Current platform_context in agent_routing.py |
| `execution-rules` | execution_rules | false | Static rules from execution.py _build_subtask_prompt + _build_fix_prompt |
| `self-heal-rules` | self_heal_rules | false | Static rules from pristine_self_heal |
| `planning-instructions` | planning_rules | false | 100-line planning prompt from planning.py |
| `review-criteria` | review_criteria | false | Review prompt from review.py |
| `triage-criteria` | triage_criteria | false | Triage prompt from triage.py |
| `supervisor-guidance-sync` | supervisor_guidance | false | Sync guidance from escalation.py |
| `supervisor-guidance-async` | supervisor_guidance | false | Async guidance from escalation.py |
| `ui-review-criteria` | ui_review_criteria | false | UI review from ai_review_quality.py |
| `ui-reviewer-system` | ui_review_criteria | false | UI reviewer system prompt |
| `summary-generation` | summary_generation | false | Summary prompt from summary_generator.py |
| `learning-extraction` | learning_extraction | false | Learning extraction from learning_extractor.py |
| `mcp-system-instruction` | mcp_instruction | false | MCP prompt from mcp_server.py |

Assignment seeds (agent_prompts):
- `coder` agent ← execution-rules, self-heal-rules
- `refactor` agent ← execution-rules, self-heal-rules
- `planner` agent ← planning-instructions
- `reviewer` agent ← review-criteria
- `qa` agent ← review-criteria
- `designer` agent ← ui-review-criteria
- etc. (map each prompt to appropriate agents)

### Also: Remove Redundant Citation Step

The `refactor.md` prompt (agent persona) has step 7 "Acknowledge Citations" which is redundant since orchestration handles citations automatically. When seeding/migrating the refactor agent's system_prompt, remove this step. The `execution-rules` prompt will include "Citations are extracted from response text automatically."

---

## Fix 3: Per-Agent Memory Curation

### Problem

All 76 memory facts injected regardless of agent type. Backend refactor agents receive frontend rules, browser test rules, CORS instructions, etc. This poisons context and confuses agents.

### Episode Tags

**Storage**: Custom Neo4j property on `:Episodic` nodes (same pattern as `injection_tier`, `trigger_task_types`, `pinned`, etc.)

**Property**: `tags: list[str]` — e.g., `["backend", "python", "testing"]`, `["frontend", "browser", "css"]`, `["coder", "refactor"]`

#### Backend Changes

**`episode_properties.py`** — Add `tags` to custom property definitions
**`episode_property_setters.py`** — Add setter for tags (`SET e.tags = $tags`)
**`episode_property_queries.py`** — Add query for filtering by tags

**New API endpoints** (in `backend/app/api/memory.py` or new `memory_tags.py`):
- `GET /api/memory/episodes/{uuid}/tags` — get episode tags
- `PUT /api/memory/episodes/{uuid}/tags` — set episode tags
- `POST /api/memory/episodes/bulk-tag` — bulk add/remove tags (list of UUIDs + add/remove tags)
- `GET /api/memory/tags` — list all distinct tags (for autocomplete/dropdown)

#### Frontend Changes

**Episodes Tab** — Tag management:
- Display tags as chips on each episode row
- Click to edit tags (tag input with autocomplete from existing tags)
- Bulk select episodes → "Add Tags" / "Remove Tags" action
- Filter episodes by tag

### Per-Agent Memory Config

**All-or-nothing toggle pattern**: Agent has `memory_config` JSON column (nullable). null = use global defaults. Non-null = full custom settings.

**Agent model change** (`backend/app/models/agent.py`):
```python
memory_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
```

**Schema** (when non-null):
```python
class AgentMemoryConfig(BaseModel):
    enabled: bool = True
    budget_enabled: bool = True
    total_budget: int = 3500
    max_mandates: int = 0          # 0 = unlimited
    max_guardrails: int = 0        # 0 = unlimited
    reference_index_enabled: bool = True
    include_tags: list[str] = []   # Whitelist (empty = no filtering)
    exclude_tags: list[str] = []   # Blacklist
```

**`include_tags` and `exclude_tags` are ALWAYS per-agent** regardless of the toggle — they have no global equivalent.

#### Filtering Logic

In `build_progressive_context()` (or `inject_progressive_context()`):

1. Resolve effective settings: agent's `memory_config` if set, else global settings
2. Fetch candidate episodes from Graphiti (existing flow)
3. **Tag filter**: For each episode, look up its `tags` property
   - If agent has `include_tags`: episode must have at least one matching tag (empty = no filter)
   - If agent has `exclude_tags`: episode must NOT have any matching tag
4. Apply tier controls (max_mandates, max_guardrails)
5. Apply budget enforcement
6. Return filtered context

#### Frontend Changes

**Agent Editor: Memory Tab**
- "Enable Custom Memory Settings" toggle (greyed out panel when off)
- When enabled: copy global defaults, show all settings as editable
  - Injection enabled toggle
  - Budget enforcement toggle
  - Token budget slider (100-10,000)
  - Max mandates/guardrails sliders (0=unlimited)
  - Reference index toggle
- **Tag filtering section** (always visible, not behind toggle):
  - Include tags: multi-select with autocomplete from existing tags
  - Exclude tags: multi-select with autocomplete from existing tags
- **Token usage display** (read-only):
  - Memory tokens (mandates + guardrails + references)
  - Prompt tokens (from assigned role prompts)
  - Total tokens per completion

#### CLI (summitflow)

- `st memory tag <uuid> --add tag1,tag2` — add tags to episode
- `st memory tag <uuid> --remove tag3` — remove tags
- `st memory tag <uuid> --set tag1,tag2` — replace all tags
- `st memory tags` — list all distinct tags

#### Backfill Script

Script to tag existing episodes based on content analysis:
- Parse episode content for domain keywords
- Auto-assign tags: backend, frontend, python, typescript, testing, git, infra, browser, css, etc.
- Run via `python -m scripts.backfill_episode_tags` or as a management command
- Safe to re-run (idempotent, only adds missing tags)

---

## Alembic Migrations

### Migration 1: Add prompts tables
- Create `prompts` table
- Create `agent_prompts` table
- Seed initial prompt data (13 prompts)
- Seed initial assignments

### Migration 2: Add memory_config to agents
- Add `memory_config` JSON column to `agents` table (nullable, default null)

---

## Files Modified (Complete List)

### Agent Hub — Backend

| File | Change |
|------|--------|
| `backend/app/models/prompt.py` | NEW: Prompt + AgentPrompt models |
| `backend/app/models/agent.py` | ADD: memory_config JSON column |
| `backend/app/models/__init__.py` | Export new models |
| `backend/app/api/prompts.py` | NEW: Prompt CRUD + assignment endpoints |
| `backend/app/api/memory_tags.py` | NEW: Episode tag management endpoints |
| `backend/app/api/schemas/prompt_schemas.py` | NEW: Request/response schemas |
| `backend/app/api/schemas/agent_schemas.py` | ADD: memory_config to agent schemas |
| `backend/app/services/prompt_service.py` | NEW: Prompt business logic |
| `backend/app/services/agent_routing.py` | MODIFY: Compose prompts from DB in inject_agent_mandates() |
| `backend/app/services/memory/context_injector.py` | MODIFY: Accept + apply agent memory_config |
| `backend/app/services/memory/context_builder.py` | MODIFY: Tag-based filtering in build_progressive_context() |
| `backend/app/services/memory/episode_properties.py` | ADD: tags property definition |
| `backend/app/services/memory/episode_property_setters.py` | ADD: tag setter |
| `backend/app/services/memory/episode_property_queries.py` | ADD: tag filter queries |
| `backend/app/services/memory/summary_generator.py` | MODIFY: Load prompt from DB instead of hardcoding |
| `backend/app/services/memory/learning_extractor.py` | MODIFY: Load prompt from DB instead of hardcoding |
| `backend/mcp_server.py` | MODIFY: Load MCP prompt from DB instead of hardcoding |
| `backend/app/api/memory_settings.py` | MODIFY: Budget-usage endpoint accepts optional agent_slug |
| `backend/prompts/refactor.md` | MODIFY: Remove citation step 7 |
| `alembic/versions/xxx_add_prompts.py` | NEW: Migration for prompts + agent_prompts + seed data |
| `alembic/versions/xxx_add_memory_config.py` | NEW: Migration for agents.memory_config |

### Agent Hub — Frontend

| File | Change |
|------|--------|
| `frontend/src/app/prompts/page.tsx` | NEW: Prompt list page |
| `frontend/src/app/prompts/new/page.tsx` | NEW: Create prompt page |
| `frontend/src/app/prompts/[slug]/page.tsx` | NEW: Edit prompt page |
| `frontend/src/app/agents/[slug]/prompts-tab.tsx` | NEW: Agent prompt assignment tab |
| `frontend/src/app/agents/[slug]/memory-tab.tsx` | NEW: Agent memory config tab |
| `frontend/src/components/memory/EpisodeTagEditor.tsx` | NEW: Tag management component |
| `frontend/src/lib/api/prompts.ts` | NEW: Prompt API client |
| `frontend/src/lib/api/memory-tags.ts` | NEW: Episode tags API client |
| `frontend/src/lib/api/memory-settings.ts` | MODIFY: Add per-agent settings support |
| `frontend/src/components/app-shell.tsx` | MODIFY: Add Prompts to NAV_ITEMS |
| `frontend/src/app/agents/[slug]/page.tsx` | MODIFY: Add Prompts + Memory tabs |

### Summitflow

| File | Change |
|------|--------|
| `backend/cli/lib/worktree.py` | MODIFY: Symlink node_modules (Fix 1) |
| `backend/app/tasks/autonomous/execution.py` | MODIFY: Strip hardcoded prompts from _build_subtask_prompt, _build_fix_prompt, pristine_self_heal |
| `backend/app/tasks/autonomous/escalation.py` | MODIFY: Strip hardcoded supervisor guidance prompts |
| `backend/app/tasks/autonomous/review.py` | MODIFY: Strip hardcoded review prompt |
| `backend/app/tasks/autonomous/planning.py` | MODIFY: Strip hardcoded planning prompt |
| `backend/app/tasks/autonomous/triage.py` | MODIFY: Strip hardcoded triage prompt |
| `backend/app/tasks/ai_review_quality.py` | MODIFY: Strip hardcoded UI review prompts |

---

## Execution Order

### Phase 1: Quick Fix (independent)
1. **Fix 1**: Worktree node_modules symlink in summitflow

### Phase 2: Backend Infrastructure (agent-hub)
2. Alembic migration: prompts + agent_prompts tables + seed data
3. Alembic migration: agents.memory_config column
4. Prompt model + AgentPrompt model
5. Prompt service (CRUD + composition)
6. Prompt API endpoints
7. Episode tag property (Neo4j) + setters + queries
8. Episode tag API endpoints
9. Modify agent_routing.py — compose prompts from DB
10. Modify context_injector/builder — accept agent memory_config + tag filtering
11. Modify summary_generator, learning_extractor, mcp_server — load from DB
12. Update agent schemas for memory_config

### Phase 3: Frontend (agent-hub)
13. Prompts management pages (list, create, edit)
14. Add Prompts to nav
15. Agent editor: Prompts tab (assignment UI)
16. Agent editor: Memory tab (per-agent config + tag filtering)
17. Episode tag management in Episodes tab

### Phase 4: Summitflow Integration
18. Strip hardcoded prompts from all 7 summitflow files
19. Verify summitflow sends only dynamic data through Agent Hub completion API

### Phase 5: Data & Verification
20. Backfill episode tags (script)
21. Update refactor.md — remove citation step 7
22. End-to-end verification

---

## Verification

### Prompt System
```bash
# Create prompt via API
curl -X POST /api/prompts -d '{"slug":"test","name":"Test","content":"..."}'
# Assign to agent
curl -X POST /api/agents/coder/prompts -d '{"prompt_slug":"execution-rules","role":"execution_rules"}'
# Verify composition
curl /api/agents/coder/preview  # Should show global + persona + role prompts
```

### Memory Curation
```bash
# Tag an episode
curl -X PUT /api/memory/episodes/{uuid}/tags -d '{"tags":["backend","python"]}'
# Configure agent memory
curl -X PUT /api/agents/refactor -d '{"memory_config":{"enabled":true,"exclude_tags":["frontend","browser"]}}'
# Verify filtered injection
# Complete with agent → check injected memory count is reduced
```

### End-to-End Pipeline
```bash
st -P summitflow list --type refactor --status pending
st autocode <small-p3-task>
st session-events --task <id> -f
# Expect: No st CLI commands, reduced memory facts, clean completion
```
