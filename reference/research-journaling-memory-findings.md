# Research Findings: Memory/Journaling Architecture Comparison

## 1. OpenClaw

### Architecture
- **Storage**: Plain Markdown files as source of truth
  - `MEMORY.md` — curated long-term stable facts
  - `memory/YYYY-MM-DD.md` — daily logs (append-only)
- **Index**: Per-agent SQLite database (`~/.openclaw/memory/{agentId}.sqlite`) with vector embeddings + FTS5, rebuilt from Markdown
- **Alt backend**: QMD (experimental) — local-first search sidecar with BM25 + vectors + reranking

### Injection
- **Memory is NOT pre-loaded into every prompt**
- Agent is given tools: `memory_search(query)` and `memory_get(path, from, lines)`
- System prompt contains guidance: "Before answering anything about prior work, decisions, dates, preferences, or todos: run memory_search"
- Bootstrap workspace files (AGENTS.md, SOUL.md, IDENTITY.md) loaded at session start, but MEMORY.md is intentionally excluded

### Budget/Limits
- Snippet max: 700 chars per search result
- Bootstrap per-file: 20KB; total: 150KB
- Trimming: 70% head + 20% tail with truncation marker
- QMD: configurable `maxInjectedChars` (e.g., 5000)

### Maintenance
- **Pre-compaction memory flush**: Before context window fills, a silent agentic turn reminds the model to write durable memory to disk
- **Temporal decay** (opt-in): `score *= e^(-ln2/halfLifeDays * ageInDays)`, default halfLife=30 days
- **Evergreen files** (MEMORY.md, non-dated files) exempt from decay
- **MMR reranking** (opt-in): Reduces near-duplicate results via Maximal Marginal Relevance (lambda=0.7)

### Relevance
- **Hybrid search**: Vector (0.7 weight) + BM25 keyword (0.3 weight)
- Post-processing pipeline: merge → temporal decay → MMR → sort → top-K
- Subagents/cron get minimal bootstrap (only AGENTS.md + TOOLS.md)

---

## 2. Auto-Claude

### Architecture
- **Primary**: Graphiti knowledge graph (embedded Kuzu/LadybugDB) with semantic search via embeddings
- **Fallback**: File-based JSON + Markdown in `.auto-claude/specs/XXX-name/memory/`
  - `codebase_map.json`, `patterns.md`, `gotchas.md`, `session_insights/session_NNN.json`
- Dual storage: tries Graphiti first, falls back to files (both succeed independently)

### Injection
- Memory appended to user message as formatted markdown section
- `get_graphiti_context(spec_dir, project_dir, subtask)` → `prompt += "\n\n" + graphiti_context`
- Sections: Relevant Knowledge, Learned Patterns, Known Gotchas, Recent Session Insights

### Budget/Limits
- `MAX_CONTEXT_RESULTS = 10` items per query
- Per-item: discoveries capped at 500 chars, file insights capped at 20 files
- Session history: only last 2-3 sessions shown
- Minimum relevance score threshold: 0.5

### Maintenance
- **No explicit pruning or summarization** — memory is cumulative and persistent
- No decay function, no TTL on episodes
- Implicit limiting via MAX_CONTEXT_RESULTS and min_score filtering

### Relevance
- Semantic search via embeddings + LLM ranking
- Query: subtask description used as search key
- Multi-level retrieval: general context (5 results) + patterns/gotchas (3 results) + session history (3 sessions)
- Episode types enable targeted retrieval (PATTERN, GOTCHA, SESSION_INSIGHT, CODEBASE_DISCOVERY, etc.)

### Memory Types (Explicit Distinction)
- **Episodic**: session insights, task outcomes (timestamped)
- **Semantic**: patterns, gotchas, codebase discoveries (reusable knowledge)
- **Procedural**: QA results, historical context
- Cross-spec sharing via PROJECT namespace (all specs share memory)

### Session Continuity
- Each session: load context → run → extract insights → save memory
- `extract_session_insights()` captures: files understood, patterns found, gotchas, recommendations
- Next session retrieves previous session's insights automatically

---

## 3. Agent Hub (Current)

### Architecture
- Journals stored as memory records (`memory_type="journal"`, `scope="agent:persona"`) in PostgreSQL
- No separate index or embedding layer for journals

### Injection
- `_fetch_journal_memories()` fetches by date range + limit
- `_format_journal_section()` renders as `<recent_journal>` XML block in system prompt
- Everything goes into system prompt unconditionally

### Budget/Limits
- 10 entry limit, 8KB character budget (after fix)
- Oldest entries dropped first when over budget

### Maintenance
- None — no decay, no summarization, no pruning
- Band-aid cap only

### Relevance
- None — fetches most recent entries regardless of task context

---

## Comparison Matrix

| Aspect | OpenClaw | Auto-Claude | Agent Hub (Current) |
|--------|----------|-------------|---------------------|
| **Storage** | Markdown files + SQLite index | Knowledge graph + file fallback | PostgreSQL records |
| **Injection point** | Via tools (on-demand) | User message (appended) | System prompt (always) |
| **Pre-loaded?** | No — agent searches when needed | Yes — per subtask | Yes — always |
| **Relevance scoring** | Hybrid vector+BM25, temporal decay, MMR | Semantic search + min_score filter | None (recency only) |
| **Budget** | 700 chars/snippet, 150KB bootstrap | 10 items, 500 chars/item | 8KB total, 10 entries |
| **Pruning/decay** | Optional temporal decay (30d half-life) | None (cumulative) | None |
| **Memory types** | Curated (MEMORY.md) vs daily logs | Episodic/semantic/procedural | Single type (journal) |
| **Pre-compaction flush** | Yes — silent turn to persist memory | No | No |

---

## Recommendations for Agent Hub

### Priority 1: Tool-Based Retrieval (from OpenClaw)

**Problem**: Journal entries are injected unconditionally into every prompt, wasting tokens when irrelevant.

**Solution**: Follow OpenClaw's pattern — provide `memory_search` and `memory_get` tools instead of pre-injecting all journals. Add system prompt guidance: "Search your journal before answering questions about past work."

**Benefits**:
- Zero journal tokens when not needed
- Agent retrieves only relevant entries
- No budget/cap management needed in prompt builder

**Implementation**: Jenny already has `mark_memory_relevant`/`mark_memory_irrelevant` tools. Add a `search_journal(query)` tool that does semantic search over journal entries, and remove the `<recent_journal>` section from the system prompt.

### Priority 2: Semantic Search over Journals (from both)

**Problem**: Current retrieval is recency-only — no relevance scoring.

**Solution**: Add embedding-based search for journal entries. Agent Hub already has a memory system with embeddings infrastructure. Extend it to support vector search over journal content.

**Approach**:
- Store embeddings for journal entries (can use existing embedding infrastructure)
- Search by task context / subtask description when building heartbeat context
- For non-heartbeat sessions, let the agent search via tools (Priority 1)

### Priority 3: Memory Type Differentiation (from Auto-Claude)

**Problem**: All journals are the same type — no distinction between observations, decisions, patterns, gotchas.

**Solution**: Auto-Claude's episode types enable targeted retrieval. Add structured memory types:
- `observation` — what happened (ephemeral, decayable)
- `pattern` — reusable insight (long-lived)
- `decision` — architectural/design choice (permanent until superseded)
- `gotcha` — pitfall to avoid (permanent)

**Benefits**: Heartbeat can retrieve patterns/gotchas specifically; chat sessions can focus on recent observations.

**Implementation**: The `entry_type` metadata field already exists in journal entries (`(mem.metadata_ or {}).get("entry_type", "observation")`). Extend retrieval to filter by type.

### Priority 4: Temporal Decay (from OpenClaw)

**Problem**: All journal entries have equal weight regardless of age.

**Solution**: Apply OpenClaw's exponential decay formula when ranking entries:
```
decayed_score = relevance_score * e^(-ln(2) / half_life_days * age_days)
```
- Default half-life: 30 days (configurable)
- "Evergreen" entries (patterns, decisions) exempt from decay
- Observations decay naturally

### Priority 5: Pre-Compaction Memory Flush (from OpenClaw)

**Problem**: When long sessions approach context limits, important observations may be lost.

**Solution**: OpenClaw triggers a silent agentic turn before context compaction: "Session nearing compaction. Store durable memories now." The agent writes lasting notes to memory files before context is cleared.

**For Agent Hub**: Before session timeout or context limit, prompt Jenny to journal important observations. This is especially relevant for long heartbeat sessions.

### Not Recommended

- **Knowledge graph (Auto-Claude's Graphiti)**: Over-engineered for our use case. PostgreSQL + embeddings is sufficient. Applied: [M:6a2ceb1c]
- **File-based fallback storage**: Our PostgreSQL storage is reliable; dual storage adds complexity without demonstrated need. Applied: [M:6a2ceb1c]
- **Cumulative memory without pruning**: Auto-Claude has no decay/pruning — this is exactly the problem we just fixed. Don't replicate it.
