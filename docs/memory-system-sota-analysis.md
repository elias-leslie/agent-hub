# Memory System SOTA Analysis & Recommendations

**Date:** 2026-01-21
**Confidence Score:** 92/100
**Analysis Scope:** JIT context injection for Claude Code / AI agents

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current System Problems](#current-system-problems)
3. [Research Sources](#research-sources)
4. [SOTA Approaches Overview](#sota-approaches-overview)
5. [Reference Implementation Analysis](#reference-implementation-analysis)
6. [Cross-Reference Matrix](#cross-reference-matrix)
7. [Validated Findings](#validated-findings)
8. [New Insights](#new-insights)
9. [Invalidated Assumptions](#invalidated-assumptions)
10. [Recommended Architecture](#recommended-architecture)
11. [Scoring Formula](#scoring-formula)
12. [Progressive Disclosure Design](#progressive-disclosure-design)
13. [Session Lifecycle](#session-lifecycle)
14. [Promotion/Demotion Rules](#promotiondemotion-rules)
15. [Implementation Action Items](#implementation-action-items)
16. [Sources & References](#sources--references)

---

## Executive Summary

This document captures comprehensive research into state-of-the-art (SOTA) memory systems for AI agents, analyzing 5 academic/industry approaches and 7 reference implementations to design an optimal JIT context injection system for Claude Code and SummitFlow/Agent Hub.

**Key Findings:**
- Tiered blocks outperform unified relevance streams for agent context
- Hybrid search (vector + BM25) is used by all production-grade systems
- Multi-factor scoring with usage tracking enables automatic relevance learning
- Progressive disclosure with 3 layers optimizes token budgets
- Bi-temporal modeling enables contradiction resolution and audit trails

---

## Current System Problems

| Problem | Impact | Root Cause |
|---------|--------|------------|
| Token limit (250) truncates mandates | Critical mandates missing | Hard cap too low |
| No semantic ranking (all score 1.0) | Irrelevant content injected | No scoring algorithm |
| Session query is generic | Poor retrieval relevance | No query expansion |
| New learnings not classified as mandates | Recent learnings never surface | `source_description: null` on save |
| No temporal decay or usage weighting | Stale content crowds out fresh | No usage tracking |

---

## Research Sources

### Academic/Industry SOTA Systems

| System | Key Innovation | Source |
|--------|----------------|--------|
| **A-MEM** | Zettelkasten-style self-organizing memory with dynamic links | [arXiv 2502.12110](https://arxiv.org/html/2502.12110v11) |
| **Continuum Memory (CMA)** | Graph substrate with semantic/temporal/structural edges, salience decay | [arXiv 2601.09913](https://arxiv.org/html/2601.09913) |
| **Graphiti/Zep** | Temporal knowledge graph, bi-temporal model, hybrid retrieval | [arXiv 2501.13956](https://arxiv.org/html/2501.13956v1) |
| **MIRIX** | 6-component architecture (Core, Episodic, Semantic, Procedural, Resource, Vault) | [arXiv 2507.07957](https://arxiv.org/html/2507.07957v1) |
| **MemGPT/Letta** | Self-editing memory with memory blocks, OS-like memory hierarchy | [Letta Docs](https://docs.letta.com/concepts/memgpt/) |

### Reference Implementations Analyzed

| Repository | Path | Focus |
|------------|------|-------|
| **Ralphy** | `summitflow/references/ralphy` | Layered prompt composition, parallel execution |
| **Auto-Claude** | `summitflow/references/Auto-Claude` | Graphiti integration, insight extraction |
| **Automaker** | `summitflow/references/automaker` | Multi-factor scoring, usage tracking |
| **Get-Shit-Done** | `summitflow/references/get-shit-done` | Fresh context segments, quality curve |
| **Claude-Mem** | `agent-hub/references/claude-mem` | Hybrid search strategies, token ROI |
| **Clawdbot** | `agent-hub/references/clawdbot` | Weighted hybrid search, adaptive pruning |
| **Graphiti** | `agent-hub/references/graphiti` | Bi-temporal edges, reranking strategies |

---

## SOTA Approaches Overview

### A-MEM (Agentic Memory)

**Architecture:** Zettelkasten-inspired interconnected knowledge network

**Key Features:**
- Memories auto-generate contextual descriptions
- Dynamic link formation between related memories
- Content and relationships evolve as new experiences emerge
- Unlike RAG, exhibits agency at memory structure level (not just retrieval)

**Indexing:** Dense vector embeddings concatenating content + keywords + tags + descriptions

**Retrieval:** Two-stage (cosine similarity → contextual augmentation via box links)

---

### Continuum Memory Architecture (CMA)

**Architecture:** Graph-based memory substrate with multi-type edges

**Key Features:**
- Semantic, temporal, and structural edges connecting fragments
- Each node retains: reinforcement history, salience, timestamps, provenance
- Selective retention based on recency, usage, salience, and integration
- Background consolidation via "dream" cycles (replay, abstraction, gist extraction)

**Temporal Handling:**
- FOLLOWED_BY edges preserve episodic sequencing
- Fragments ingested days/weeks apart remain addressable
- Temporal classifiers: episodic, habitual, timeless

**Decay Mechanism:**
- Salience analysis yields scalar governing retention
- Low-salience, low-reinforcement entries evicted at capacity
- Retrieval-induced mutation: accessed nodes reinforced, near-misses suppressed

---

### Graphiti/Zep (Temporal Knowledge Graph)

**Architecture:** Bi-temporal knowledge graph with hybrid retrieval

**Key Features:**
- Real-time incremental updates (no batch recomputation)
- Bi-temporal data model (event time + ingestion time)
- Hybrid retrieval: embeddings + BM25 + graph traversal
- P95 latency: 300ms (no LLM calls during retrieval)

**Bi-Temporal Model:**
```
valid_at:   When the fact became true in reality
invalid_at: When the fact stopped being true
expired_at: When the system learned about invalidation
```

**Contradiction Resolution:**
- LLM compares new edges against semantically related existing edges
- Temporally overlapping contradictions trigger invalidation
- Affected edges get `invalid_at` set to new edge's `valid_at`

**Performance:** 94.8% on Deep Memory Retrieval benchmark (vs MemGPT's 93.4%)

---

### MIRIX (Multi-Agent Memory System)

**Architecture:** 6-component memory with specialized managers

**Components:**
1. **Core Memory**: Persona + human blocks, auto-rewrite at 90% capacity
2. **Episodic Memory**: Time-stamped events with actor, summary, details
3. **Semantic Memory**: Abstract knowledge independent of time
4. **Procedural Memory**: Goal-directed workflows and scripts
5. **Resource Memory**: Documents, transcripts, multimedia
6. **Knowledge Vault**: Secure storage with access controls

**Retrieval:** Active retrieval - agent generates "current topic" from input, uses it to search each component

**Multi-Agent Coordination:** 8 agents (Meta Manager + 6 Memory Managers + Chat Agent)

---

### MemGPT/Letta (LLM Operating System)

**Architecture:** OS-like memory hierarchy with self-editing

**Key Features:**
- Context window treated as constrained memory resource
- Memory hierarchy: in-context (RAM) ↔ archival/recall (disk)
- Self-editing via tool calling (memory_replace, memory_insert, memory_rethink)
- Creates illusion of unlimited memory within fixed context limits

**Memory Blocks:**
- Break context into purposeful units (persona, human, etc.)
- Blocks are persisted and agent-editable
- Archival memory backed by vector database (Chroma/pgvector)

**Tools:**
- `archival_memory_insert` / `archival_memory_search`
- `conversation_search` / `conversation_search_date`

---

## Reference Implementation Analysis

### Ralphy

**Context Injection:** Layered prompt composition
```typescript
parts = [
  "## Project Context\n" + loadProjectContext(),
  "## Rules (you MUST follow these)\n" + rules.join("\n"),
  "## Boundaries\n" + boundaries.join("\n"),
  "## Task\n" + task,
  "## Instructions\n" + instructions.join("\n")
]
```

**Ranking:** None (FIFO task order)

**Token Management:** Tracking only, no budget enforcement

**Key Insight:** Simple works for basic orchestration, but no learning/adaptation

---

### Auto-Claude

**Context Injection:** Graphiti-based semantic search before agent start
```python
# Searches subtask description against knowledge graph
# Retrieves 3 types: context items, patterns/gotchas, session history
context_items = graphiti.search(subtask_description, num_results=5)
```

**Ranking:** Semantic similarity with min_score filtering (0.5 default)

**Progressive Disclosure (4 tiers):**
1. Relevant Knowledge (10 items, 500 char each)
2. Learned Patterns (3 items)
3. Known Gotchas (3 items)
4. Session History (2 sessions, 3 recommendations each)

**Token Management:** MAX_CONTEXT_RESULTS=10, 500 char truncation per item

**Key Insight:** Dual-storage (Graphiti + file fallback) provides resilience

---

### Automaker

**Context Injection:** Smart memory file selection based on task context

**Scoring Formula:**
```typescript
score = (
  tagScore × 3 +
  relevantToScore × 2 +
  summaryScore × 1 +
  categoryScore × 4
) × importance × usageScore

usageScore = 0.5 + (referenced/loaded × 0.3) + (success/referenced × 0.2)
```

**Progressive Disclosure (3 stages):**
1. Always include `gotchas.md`
2. Add high-importance files (>= 0.9)
3. Add top-scoring files up to `maxMemoryFiles` (default: 5)

**Metadata (YAML frontmatter):**
```yaml
tags: [authentication, security]
relevantTo: [auth, tokens]
importance: 0.9
usageStats:
  loaded: 10
  referenced: 8
  successfulFeatures: 6
```

**Key Insight:** Usage tracking enables learning what context actually helps

---

### Get-Shit-Done (GSD)

**Context Injection:** @-reference lazy loading
```markdown
<execution_context>
  @~/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>
<context>
  Plan: @{plan_path}
  Project state: @.planning/STATE.md
</context>
```

**Ranking:** Dependency graph via machine-readable frontmatter
```yaml
requires:
  - phase: auth-setup
    provides: JWT token generation
provides:
  - API rate limiting middleware
affects: [api-endpoints, user-service]
```

**Progressive Disclosure (multi-tier memory):**
- STATE.md: Short-term (<100 lines, digest format)
- PROJECT.md: Project-level (requirements, decisions, constraints)
- ROADMAP.md: Execution (phases, completion status)
- Phase-specific: CONTEXT.md, RESEARCH.md, PLAN.md, SUMMARY.md

**Token Management (Quality Degradation Curve):**
```
0-30%:  Peak quality
30-50%: Good quality
50-70%: Degrading quality
70%+:   Poor quality
```

**Fresh Context Pattern:**
```
Orchestrator: ~10-15% context
Subagent 1: Fresh 200k context (tasks 1-3)
Subagent 2: Fresh 200k context (tasks 4-6)
```

**Key Insight:** Quality impossible to degrade in isolated segments

---

### Claude-Mem

**Context Injection:** Three-layer progressive disclosure

**Search Strategies:**
1. **ChromaDB Semantic**: Vector similarity with 90-day recency window
2. **SQLite Metadata**: Filter-only when no query text
3. **Hybrid**: Metadata filter → Chroma ranking → intersection

**Progressive Disclosure:**
- **Layer 1 (Index)**: 50-100 tokens per result (metadata only)
- **Layer 2 (Timeline)**: Chronological context around anchor
- **Layer 3 (Details)**: Full observation on demand

**Token Economics:**
```typescript
{
  totalDiscoveryTokens: 15000,  // Cost to learn this
  totalReadTokens: 200,         // Cost to inject
  savings: 14800,               // ROI
  savingsPercent: 98.7
}
```

**Key Insight:** Agent decides what's relevant from index (not pre-fetched)

---

### Clawdbot

**Context Injection:** Bootstrap files + auto-recall + memory tools

**Hybrid Search:**
```
finalScore = vectorWeight × vectorScore + textWeight × textScore
           = 0.7 × cosine_similarity + 0.3 × bm25_score
```

**Candidate Pool Strategy:** Retrieve 4x candidates from each method, then merge

**Token Budget (3-tier):**
```javascript
CONTEXT_WINDOW_HARD_MIN = 16_000    // Never go below
CONTEXT_WINDOW_WARN_BELOW = 32_000  // Warning zone
reserveTokensFloor = 20_000         // Reserve for new context
softThresholdTokens = 4_000         // Trigger point
```

**Deduplication:**
- Content hash caching (prevents re-embedding)
- 95% similarity check before storing new memories

**Key Insight:** Adaptive pruning (soft-trim → hard-clear) based on context ratio

---

### Graphiti (Reference Implementation)

**Knowledge Graph Structure:**
- **Nodes:** EntityNode, EpisodicNode, CommunityNode, SagaNode
- **Edges:** RELATES_TO (bi-temporal), MENTIONS, HAS_MEMBER, NEXT_EPISODE

**Bi-Temporal Fields:**
```python
class EntityEdge:
    valid_at: datetime      # When fact became true
    invalid_at: datetime    # When fact ended
    expired_at: datetime    # When system learned
```

**Hybrid Retrieval:**
1. Semantic search (cosine on embeddings)
2. BM25 keyword search (Lucene fulltext)
3. Graph traversal (BFS up to depth 3)

**Reranking Strategies:**
- **RRF**: Reciprocal Rank Fusion across methods
- **Cross-Encoder**: Neural reranking via pairs
- **MMR**: Maximal Marginal Relevance (relevance vs diversity)
- **Node Distance**: Boost results near center node

**Deduplication:**
- MinHash + LSH with 0.9 Jaccard threshold
- 32 hash permutations, 4-band structure
- Entropy-based filtering for reliable matches

**Key Insight:** Episode mentions tracking enables relevance by frequency/recency

---

## Cross-Reference Matrix

| Feature | Ralphy | Auto-Claude | Automaker | GSD | Claude-Mem | Clawdbot | Graphiti |
|---------|--------|-------------|-----------|-----|------------|----------|----------|
| **Semantic Search** | ❌ | ✅ Graphiti | ✅ Terms | ❌ | ✅ ChromaDB | ✅ sqlite-vec | ✅ Neo4j |
| **BM25/Keyword** | ❌ | ❌ | ❌ | ❌ | ✅ FTS | ✅ FTS5 | ✅ Lucene |
| **Hybrid Search** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ (0.7/0.3) | ✅ + BFS |
| **Tiered Blocks** | ✅ | ✅ 4-tier | ✅ 3-stage | ✅ Multi-tier | ✅ 3-layer | ✅ Bootstrap→Recall | ❌ Unified |
| **Relevance Scoring** | ❌ FIFO | ✅ min_score | ✅ Multi-factor | ✅ Frontmatter | ✅ Distance | ✅ Weighted | ✅ Rerankers |
| **Usage Tracking** | ❌ | ❌ | ✅ | ❌ | ✅ Token ROI | ❌ | ✅ Episodes |
| **Temporal Decay** | ❌ | ❌ | ❌ | ❌ | ✅ 90-day | ❌ | ✅ Bi-temporal |
| **Token Budget** | Track | 10×500 | Thinking | Quality curve | Configurable | 3-tier | ❌ |
| **Auto-Promotion** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Memory Links** | ❌ | ❌ | relatedFiles | requires/provides | ❌ | ❌ | ✅ Edges |

---

## Validated Findings

### 1. Tiered Blocks > Unified Stream

**Evidence:** 6 of 7 implementations use tiered/layered approaches

**Examples:**
- Auto-Claude: Knowledge → Patterns → Gotchas → Session History
- Automaker: Gotchas always → High-importance → Scored
- GSD: STATE → PROJECT → ROADMAP → Phase-specific
- Claude-Mem: Index → Timeline → Details

**Why it works:** Different content types have different failure modes:
- Missing a mandate: Catastrophic (breaks invariants)
- Missing a reference: Recoverable (agent can ask or search)

---

### 2. Hybrid Search (Vector + BM25)

**Evidence:** All production-grade systems use hybrid

**Implementations:**
- Clawdbot: 0.7 vector + 0.3 BM25 (configurable)
- Claude-Mem: ChromaDB + SQLite FTS with strategy selection
- Graphiti: Semantic + BM25 + Graph traversal + 4 reranker options

**Best Practice (from Clawdbot):**
```
1. Vector: top (maxResults × 4) by cosine similarity
2. BM25: top (maxResults × 4) by FTS5 rank
3. Union candidates by chunk ID
4. Compute weighted final score
```

---

### 3. Multi-Factor Scoring

**Best formula (from Automaker):**
```python
score = (
    tag_match × 3 +
    relevantTo_match × 2 +
    summary_match × 1 +
    category_match × 4
) × importance × usage_score

usage_score = 0.5 + (referenced/loaded × 0.3) + (success/referenced × 0.2)
```

**Graphiti additions:**
- Episode mentions frequency/recency
- Node distance in graph
- Cross-encoder neural reranking

---

### 4. Progressive Disclosure Pattern

**Best implementation (from Claude-Mem):**
- **Layer 1 (Index):** 50-100 tokens per result, just metadata
- **Layer 2 (Timeline):** Chronological context around anchor
- **Layer 3 (Details):** Full observation on demand

**GSD addition:** Quality degradation curve awareness
```
0-30%:  Peak quality
30-50%: Good quality
50-70%: Degrading
70%+:   Poor quality
```

---

## New Insights

### 1. Bi-Temporal Model for Memory Evolution (from Graphiti)

```python
class TemporalMemory:
    valid_at: datetime      # When fact became true in reality
    invalid_at: datetime    # When fact stopped being true
    expired_at: datetime    # When system learned about invalidation
```

**Benefits:**
- Point-in-time queries ("What did we know on Jan 15?")
- Contradiction resolution (new facts invalidate old)
- Audit trails for debugging

---

### 2. Fresh Context Per Segment (from GSD)

```
Orchestrator: ~10-15% context usage
  ├─ Subagent 1: Fresh 200k context (tasks 1-3)
  ├─ Checkpoint: Human verify
  ├─ Subagent 2: Fresh 200k context (tasks 4-6)
  └─ Aggregate results
```

**Why it matters:** Quality impossible to degrade in isolated segments. Each agent starts at 0%.

---

### 3. Usage-Based Learning with ROI Tracking (from Claude-Mem + Automaker)

```python
# Claude-Mem
token_economics = {
    "discovery_tokens": 15000,  # Tokens spent learning this
    "read_tokens": 200,         # Tokens to inject
    "savings": 14800,           # ROI
    "savings_percent": 98.7
}

# Automaker
usage_stats = {
    "loaded": 10,              # Times included in context
    "referenced": 8,           # Times agent actually used it
    "successful_features": 6   # Times it led to success
}
```

---

### 4. Dependency Graphs via Frontmatter (from GSD)

```yaml
# In SUMMARY.md files
requires:
  - phase: auth-setup
    provides: JWT token generation
provides:
  - API rate limiting middleware
affects: [api-endpoints, user-service]
```

**Why it matters:** Enables automatic context assembly for dependent phases without semantic search.

---

### 5. Deduplication Strategy (from Graphiti + Clawdbot)

**Graphiti:** MinHash + LSH with 0.9 Jaccard threshold
- 3-gram shingles for name matching
- 32 hash permutations, 4-band structure
- Entropy-based filtering

**Clawdbot:**
- Content hash caching (prevents re-embedding)
- 95% similarity check before storing new memories

---

## Invalidated Assumptions

### 1. "Token Limit is THE Constraint" (Partially Invalidated)

**New insight:** The constraint isn't the limit—it's the **quality degradation curve**.

**From GSD:**
```
0-30%:  Peak quality
30-50%: Good quality
50-70%: Degrading
70%+:   Poor quality
```

**Solution:** Don't try to pack more into the limit. Use fresh context segments.

---

### 2. "Mandates Should Always Inject" (Partially Invalidated)

**New insight from Automaker:** Even "always inject" items should have an importance threshold.

**Correct pattern:**
1. **Always:** Gotchas (critical edge cases)
2. **High-importance:** Core mandates (>= 0.9)
3. **Scored:** Everything else by relevance

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     MEMORY SUBSTRATE (Neo4j + SQLite)               │
├─────────────────────────────────────────────────────────────────────┤
│  Nodes: EntityNode, EpisodeNode, CommunityNode, SagaNode           │
│  Edges: RELATES_TO (bi-temporal), MENTIONS, HAS_MEMBER, NEXT       │
│  Fields: uuid, embedding, valid_at, invalid_at, expired_at,        │
│          importance, usage_stats{loaded, referenced, success}      │
│  Indices: Vector (embeddings), FTS5 (content), created_at          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     HYBRID RETRIEVAL LAYER                          │
├─────────────────────────────────────────────────────────────────────┤
│  1. Query Expansion (LLM generates 2-3 retrieval queries)          │
│  2. Parallel Search:                                                │
│     • Vector search (cosine similarity on embeddings)               │
│     • BM25 keyword search (FTS5 on content, tags, names)           │
│     • Graph traversal (BFS up to depth 3 from relevant nodes)      │
│  3. Candidate Pool: 4x over-fetch, then merge                      │
│  4. Reranking: RRF + optional cross-encoder                        │
│  5. Filtering: min_score >= 0.35, recency_window <= 90 days        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  MULTI-FACTOR SCORING                               │
├─────────────────────────────────────────────────────────────────────┤
│  base_score = (                                                     │
│      0.4 × semantic_similarity +                                    │
│      0.2 × bm25_score +                                            │
│      0.2 × recency_decay(half_life=7d for ref, 30d for mandate) +  │
│      0.2 × usage_score(loaded, referenced, success)                │
│  )                                                                  │
│                                                                     │
│  final_score = base_score × importance_multiplier                  │
│                                                                     │
│  importance_multiplier = {mandate: 2.0, guardrail: 1.5, ref: 1.0}  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PROGRESSIVE DISCLOSURE (3-TIER)                    │
├─────────────────────────────────────────────────────────────────────┤
│  TIER 1: MANDATES (always inject, ~150 tokens)                     │
│    • Gotchas always included                                       │
│    • High-importance (>= 0.9) golden standards                     │
│    • Format: [M:uuid8] Content (score: 0.95)                       │
│                                                                     │
│  TIER 2: GUARDRAILS (inject if relevant, ~100 tokens)              │
│    • Anti-patterns matching query context                          │
│    • Format: [G:uuid8] In {context}, avoid {anti-pattern}         │
│                                                                     │
│  TIER 3: REFERENCE (inject top-k by score, ~150 tokens)            │
│    • Patterns, workflows, past learnings                           │
│    • Format: bullet list sorted by score                           │
│                                                                     │
│  Total target: ~400 tokens (increased from 250)                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Scoring Formula

### Recommended Implementation

```python
def score_memory(memory, query_embedding, bm25_score, current_time):
    """
    Multi-factor scoring combining semantic, keyword, temporal, and usage signals.
    """
    # Semantic relevance (0-1)
    semantic = cosine_similarity(memory.embedding, query_embedding)

    # Keyword relevance (0-1, normalized BM25)
    keyword = 1 / (1 + max(0, bm25_score))

    # Recency decay: half-life varies by tier
    half_life = 30 if memory.tier == 'mandate' else 7  # days
    days_since_use = (current_time - memory.last_used).days
    recency = 0.5 ** (days_since_use / half_life)

    # Usage score (learning from past effectiveness)
    if memory.usage_stats.loaded == 0:
        usage = 0.5  # Neutral for new items
    else:
        reference_rate = memory.usage_stats.referenced / memory.usage_stats.loaded
        success_rate = (
            memory.usage_stats.success / memory.usage_stats.referenced
            if memory.usage_stats.referenced > 0 else 0
        )
        usage = 0.5 + (reference_rate * 0.3) + (success_rate * 0.2)

    # Base score (weighted combination)
    base_score = (
        0.4 * semantic +
        0.2 * keyword +
        0.2 * recency +
        0.2 * usage
    )

    # Importance multiplier (not additive—mandates always surface)
    importance_multiplier = {
        'mandate': 2.0,
        'guardrail': 1.5,
        'reference': 1.0
    }[memory.tier]

    return base_score * importance_multiplier
```

### Hybrid Search Weights

```python
HYBRID_WEIGHTS = {
    'vector': 0.7,   # Semantic understanding
    'bm25': 0.3,     # Exact keyword matching
}

CANDIDATE_MULTIPLIER = 4  # Retrieve 4x, then merge
```

---

## Progressive Disclosure Design

### Tier 1: Mandates (~150 tokens)

**Always inject:**
- Gotchas (critical edge cases)
- Golden standards with importance >= 0.9

**Format:**
```markdown
## Mandates
- [M:3603dc66] CLI Tool Preferences: Use rg instead of grep (score: 0.95)
- [M:d1c23d03] Always write tests for new code (score: 0.92)
```

### Tier 2: Guardrails (~100 tokens)

**Inject if relevant to query:**
- Anti-patterns matching context
- Filtered by min_score >= 0.35

**Format:**
```markdown
## Guardrails
- [G:c1ca13eb] In Error Handling, avoid swallowing async errors
- [G:cde7486e] In Error Handling, avoid empty catch blocks
```

### Tier 3: Reference (~150 tokens)

**Inject top-k by score:**
- Patterns, workflows, past learnings
- Semantic relevance to current task

**Format:**
```markdown
## Reference
- SummitFlow CLI explains workflow commands
- st CLI has active workflow commands
- API routes use /api/v1 prefix in this codebase
```

### Footer

```markdown
When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]
```

---

## Session Lifecycle

### Session Start

```python
def on_session_start(user_message, project_id):
    # 1. Generate retrieval queries (LLM-powered)
    queries = llm.generate_retrieval_queries(user_message, n=3)

    # 2. Hybrid search with multi-factor scoring
    candidates = []
    for query in queries:
        candidates.extend(hybrid_search(query, project_id))

    # 3. Deduplicate and re-rank
    ranked = rerank_rrf(deduplicate(candidates))

    # 4. Build 3-tier context
    context = build_progressive_context(ranked, token_budget=400)

    # 5. Inject into session
    return inject_context(context)
```

### Mid-Session

```python
def on_mid_session(context_usage_percent, topic_embedding):
    # Track quality degradation
    if context_usage_percent > 0.5:
        log_warning("Context at {:.0%}, quality may degrade".format(context_usage_percent))

    # Detect topic shift (re-inject if needed)
    if embedding_distance(topic_embedding, session.initial_topic) > 0.5:
        fresh_context = retrieve_for_topic(topic_embedding)
        inject_supplementary(fresh_context)

    # Agent can save learnings (append-only)
    # save_learning(content, confidence) available as tool
```

### Session End

```python
def on_session_end(session_transcript, retrieved_memories):
    # 1. Extract insights from session (LLM-powered)
    insights = llm.extract_insights(session_transcript)

    # 2. Update usage stats for retrieved memories
    for memory in retrieved_memories:
        memory.usage_stats.loaded += 1
        if was_referenced(memory, session_transcript):
            memory.usage_stats.referenced += 1
        if session.success:
            memory.usage_stats.success += 1

    # 3. Run promotion/demotion rules
    for memory in all_memories:
        new_tier = evaluate_promotion_rules(memory)
        if new_tier != memory.tier:
            promote_or_demote(memory, new_tier)

    # 4. Invalidate contradicted facts (bi-temporal)
    for new_fact in insights.facts:
        contradictions = find_contradictions(new_fact)
        for old_fact in contradictions:
            old_fact.invalid_at = new_fact.valid_at
```

---

## Promotion/Demotion Rules

### Promotion: Reference → Guardrail

```python
if (
    memory.usage_stats.referenced >= 10 and
    memory.avg_relevance_score >= 0.7
):
    promote(memory, 'guardrail')
```

### Promotion: Guardrail → Mandate

```python
if (
    memory.usage_stats.referenced >= 25 and
    memory.usage_stats.success >= 20
) or memory.human_confirmed:
    promote(memory, 'mandate')
```

### Demotion: Any → Archive

```python
if (
    days_since_last_used(memory) > 90 and
    memory.usage_stats.referenced < 5
):
    demote(memory, 'archive')
```

### Invalidation: Bi-Temporal Contradiction

```python
if new_fact.contradicts(existing_fact):
    existing_fact.invalid_at = new_fact.valid_at
    existing_fact.expired_at = datetime.now()
```

---

## Implementation Action Items

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **P0** | Fix save-learning API to set `source_description` with mandate flag | Low | High |
| **P0** | Promote existing learnings (st work, st close, schema, browser) to golden standards | Low | High |
| **P1** | Add usage tracking fields (loaded, referenced, success) to memory schema | Medium | High |
| **P1** | Implement hybrid search (vector + BM25) with 0.7/0.3 weights | Medium | High |
| **P1** | Increase mandate token limit from 250 to 400 | Low | Medium |
| **P2** | Add multi-factor scoring formula | Medium | Medium |
| **P2** | Add 90-day recency window filter | Low | Medium |
| **P2** | Implement LLM query expansion for session start | Medium | Medium |
| **P3** | Add bi-temporal model for contradictions (valid_at, invalid_at, expired_at) | High | Medium |
| **P3** | Implement automatic promotion/demotion based on usage | High | High |
| **P3** | Add memory links (requires/provides/affects) for dependency graphs | High | Medium |

---

## Sources & References

### Research Papers

- **A-MEM**: [arXiv 2502.12110](https://arxiv.org/html/2502.12110v11) - Agentic Memory for LLM Agents
- **CMA**: [arXiv 2601.09913](https://arxiv.org/html/2601.09913) - Continuum Memory Architectures
- **Zep**: [arXiv 2501.13956](https://arxiv.org/html/2501.13956v1) - Temporal Knowledge Graph Architecture
- **MIRIX**: [arXiv 2507.07957](https://arxiv.org/html/2507.07957v1) - Multi-Agent Memory System

### Industry Resources

- [Graphiti - Neo4j Blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Memory Blocks - Letta](https://www.letta.com/blog/memory-blocks)
- [Agent Memory - Letta](https://www.letta.com/blog/agent-memory)
- [2026 Memory Stack for Enterprise Agents](https://alok-mishra.com/2026/01/07/a-2026-memory-stack-for-enterprise-agents/)
- [Progressive Disclosure - NN/g](https://www.nngroup.com/articles/progressive-disclosure/)
- [Progressive Disclosure - IxDF](https://www.interaction-design.org/literature/topics/progressive-disclosure)
- [Context Engineering Guide - Mem0](https://mem0.ai/blog/context-engineering-ai-agents-guide)
- [Memory Management - Letta Docs](https://docs.letta.com/advanced/memory-management/)

### Reference Implementations

- `summitflow/references/ralphy` - Layered prompt composition
- `summitflow/references/Auto-Claude` - Graphiti integration
- `summitflow/references/automaker` - Multi-factor scoring
- `summitflow/references/get-shit-done` - Fresh context segments
- `agent-hub/references/claude-mem` - Hybrid search strategies
- `agent-hub/references/clawdbot` - Weighted hybrid search
- `agent-hub/references/graphiti` - Bi-temporal knowledge graph

---

## Appendix: Confidence Assessment

**Current Score: 92/100**

**Why not higher:**
1. Haven't implemented and tested promotion/demotion rules in production
2. Query expansion cost (~100 tokens) may not be worth it for simple sessions
3. Cross-encoder reranking adds latency that may not be acceptable for session start

**What would increase to 95+:**
- A/B test the scoring formula weights
- Validate 90-day recency window is right for coding context
- Test promotion thresholds empirically
- Measure latency impact of hybrid search vs simple vector search
