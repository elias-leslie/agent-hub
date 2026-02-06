# Johnny Implementation Context

**Created:** 2026-02-05
**Memory Episode:** `c6b88828` (searchable via `st memory get c6b88828`)

## What is Johnny?

Johnny is the renamed/enhanced memory system for Agent Hub, named after the 1995 cyberpunk film "Johnny Mnemonic" (Keanu Reeves as a data courier with a cybernetic brain implant).

## Key Decisions Made

### 1. Naming
- **Name:** Johnny (not Engram, Cortex, Mnemos, or Recall - all have conflicts)
- Full rename across entire stack: backend, frontend, API routes, DB tables, CLI commands

### 2. Storage Architecture (Consulted Gemini Pro)
- **Keep dual-DB:** Neo4j/Graphiti + PostgreSQL (this is SOTA for 2026)
- **NO SQLite local cache** - avoids split-brain state fragmentation
- Redis available for hot cache if latency becomes an issue
- Rationale: GraphRAG (graph + vector) is industry standard; Mem0/Zep both use graph structures

### 3. Scopes
- GLOBAL (existing)
- PROJECT (existing)
- **TASK (new)** - completing partially implemented task-level scoping
- Hierarchical queries: task → project → global

### 4. Capture Sources (ObservationSource enum)
| Source | Integration |
|--------|-------------|
| `claude_code` | ~/.claude/plugins/johnny/ hooks (PostToolUse, SessionStart, Stop) |
| `agent_hub_chat` | Hook into chat message flow |
| `summitflow_task` | Subscribe to step_complete/step_fail events |
| `agentic_execution` | Celery task completion events |
| `manual` | API/CLI |

### 5. Observation Types (ObservationType enum)
- tool_use, decision, change, learning, error, pattern

### 6. Frontend Dashboard
**Location:** ~/agent-hub/frontend/src/app/johnny/

**5 Tabs:**
1. **Episodes** - Enhanced existing memory list
2. **Timeline** - Chronological view by date (NEW)
3. **Sessions** - Session history + continuity (NEW)
4. **Capture** - Real-time SSE observation stream (NEW)
5. **Analytics** - Usage metrics, A/B results, tier stats (NEW)

### 7. Key Features to Implement
- Auto-capture from all interfaces
- Session summary auto-generation (provider-agnostic LLM)
- Cross-session continuity ("Previously on..." injection)
- Privacy filtering (`<private>` tag stripping)
- Task-level scoping

## Skills to Use

| Domain | Skills |
|--------|--------|
| Backend API | `/fastapi`, `/sqlalchemy-2-async`, `/pydantic` |
| Database | `/alembic-migrations`, `/neo4j-cypher-guide` |
| Frontend | `/frontend-design`, `/optimized-nextjs-typescript` |
| Testing | `/pytest`, `/python-testing-patterns` |
| Claude Code plugins | `/hook-development` |
| Async patterns | `/async-python-patterns`, `/celery-expert` |

## Task Files Location

Task JSON files are in: `~/agent-hub/cc_native_tasks/194d416d-5d70-4c02-aae2-3d1bb26f238e/`

**23 Tasks (#39-#61):**

### Phase 1: Core Rename
- #39: Backend service rename (START - no blockers)
- #40: API routes rename
- #41: Database migration
- #42: Frontend API client
- #43: Frontend page/components
- #58: CLI commands
- #59: Documentation + existing episodes

### Phase 2: New Features
- #44: Task-level scoping
- #50: Unified Observation schema
- #57: Privacy filtering

### Phase 3: Dashboard (5 tabs)
- #45: Tab navigation structure
- #46: Timeline tab
- #47: Sessions tab
- #48: Capture tab (SSE)
- #49: Analytics tab

### Phase 4: Capture Layer
- #51: Claude Code hooks plugin
- #52: SummitFlow event capture
- #53: Agent Hub chat capture
- #54: Agentic execution capture

### Phase 5: Session Features
- #55: Session summary auto-generation
- #56: Cross-session continuity

### Phase 6: Verification
- #60: Comprehensive verification (blocked by ALL implementation tasks)
- #61: Final documentation + memory episodes

## To Load Tasks

Read each JSON file and use TaskCreate to recreate them:

```bash
# Example: Read task #39
cat ~/agent-hub/cc_native_tasks/194d416d-5d70-4c02-aae2-3d1bb26f238e/39.json
```

Or ask Claude to: "Load and recreate all tasks from ~/agent-hub/cc_native_tasks/194d416d-5d70-4c02-aae2-3d1bb26f238e/"

## Critical Paths

```
#39 (Backend rename) - START HERE
 ├── #40 (API routes) → #42 (Frontend API) → #43 (Frontend page) → #45 (Tabs)
 │                                                                  ├── #46 (Timeline)
 │                                                                  ├── #47 (Sessions) → #55 (Summary) → #56 (Continuity)
 │                                                                  ├── #48 (Capture SSE)
 │                                                                  └── #49 (Analytics)
 ├── #41 (DB migration)
 ├── #44 (Task scoping)
 ├── #50 (Observation schema) → #57 (Privacy) → #51 (CC Plugin)
 │                            ├── #52 (SummitFlow capture)
 │                            ├── #53 (Chat capture)
 │                            └── #54 (Agentic capture)
 └── #58 (CLI) → #59 (Docs)

All above → #60 (Verification) → #61 (Final docs)
```

## File Locations Summary

| Component | Location |
|-----------|----------|
| Backend service | ~/agent-hub/backend/app/services/memory/ → johnny/ |
| Backend API | ~/agent-hub/backend/app/api/memory.py → johnny.py |
| Frontend page | ~/agent-hub/frontend/src/app/memory/ → johnny/ |
| Frontend components | ~/agent-hub/frontend/src/components/memory/ → johnny/ |
| Frontend API client | ~/agent-hub/frontend/src/lib/memory-*.ts → johnny-*.ts |
| Frontend hooks | ~/agent-hub/frontend/src/hooks/use-memory.ts → use-johnny.ts |
| CLI commands | ~/summitflow/cli/commands/memory.py → johnny.py |
| CC Plugin | ~/.claude/plugins/johnny/ (new) |

## Gap Analysis Reference

The full gap analysis compared claude-mem (~/agent-hub/references/claude-mem/) with Agent Hub's memory system. Key gaps being addressed:

1. **CRITICAL:** No automatic tool observation capture → Adding CC hooks
2. **CRITICAL:** No session summary generation → Adding auto-summary
3. **CRITICAL:** No hook infrastructure → Building CC plugin
4. **SIGNIFICANT:** No timeline/chronological view → Adding Timeline tab
5. **SIGNIFICANT:** No cross-session continuity → Adding "Previously on" injection
6. **SIGNIFICANT:** No file change tracking → Adding to observations

## Remember

- All paths are absolute ~/agent-hub/ paths
- Use `/frontend-design` skill for ALL UI work
- Use `/commit_it` after each task completion
- Run `rebuild.sh` (in agent-hub) after changes
- Check context levels: >= 60% → /compact, >= 75% → /commit_it then /compact
