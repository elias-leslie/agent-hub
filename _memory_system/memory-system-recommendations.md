# Memory System Recommendations

**Date:** 2026-01-23
**Status:** Research Complete
**Related Task:** task-2c3a338a (Memory System Optimization)

## Executive Summary

Comprehensive review of Agent Hub's episode creation system identified 12 improvements ranging from quick fixes to SOTA architecture changes. Current system works but has inconsistent validation, no token budgeting, and a DRY violation.

**Key Finding:** 15 of 16 production callers properly use `MemoryService.add_episode()`. Only `store_golden_standard()` bypasses it due to a missing `name` parameter.

---

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Recommendations](#recommendations)
3. [Reference: Auto-Claude Patterns](#reference-auto-claude-patterns)
4. [Reference: Gemini Pro Consultation](#reference-gemini-pro-consultation)
5. [File References](#file-references)

---

## Current Architecture

### Episode Creation Call Graph

```
                                    ┌─────────────────────┐
                                    │   graphiti.add_     │
                                    │      episode()      │
                                    └──────────┬──────────┘
                                               │
              ┌────────────────────────────────┼────────────────────────────────┐
              │                                │                                │
              ▼                                ▼                                │
   ┌──────────────────┐           ┌──────────────────────┐                     │
   │ store_golden_    │           │ MemoryService.       │                     │
   │   standard()     │           │   add_episode()      │                     │
   │                  │           │                      │                     │
   │ ✓ dedup          │           │ ✗ no dedup           │                     │
   │ ✓ formatting     │           │ ✗ no formatting      │                     │
   │ ✓ linking        │           │ ✗ hardcoded name     │                     │
   └──────────────────┘           └──────────┬───────────┘                     │
          │                                  │                                 │
          │ BYPASS                           │ USED BY 15 CALLERS              │
          │ (DRY violation)                  │                                 │
          └──────────────────────────────────┴─────────────────────────────────┘
```

### Current Data Quality Issues (as of 2026-01-23)

| Issue | Count | Severity |
|-------|-------|----------|
| Total episodes | 186 | - |
| Orphaned (no entity_edges) | 32 | Medium (mostly valid content) |
| Debug/test episodes | 1 | Low |
| Duplicate content | 1 pair | Low |
| Legacy groups | 0 | Resolved by task-2c3a338a |

---

## Recommendations

### 1. Fix DRY Violation: Add `name` Parameter to `add_episode()`

**Effort:** 10 lines
**Impact:** Low (technical debt)
**Priority:** Do Now

**Problem:**
`store_golden_standard()` bypasses `MemoryService.add_episode()` because the service hardcodes the episode name:

```python
# service.py:212 - name is hardcoded
name=f"{source.value}_{reference_time.isoformat()}"
```

Golden standards need custom names from `EpisodeFormatter`, so they call Graphiti directly.

**Solution:**

```python
# backend/app/services/memory/service.py
async def add_episode(
    self,
    content: str,
    source: MemorySource = MemorySource.CHAT,
    source_description: str | None = None,
    reference_time: datetime | None = None,
    name: str | None = None,  # NEW: optional custom name
) -> str:
    reference_time = reference_time or utc_now()
    name = name or f"{source.value}_{reference_time.isoformat()}"
    # ... rest unchanged
```

Then update `store_golden_standard()` to call through the service.

**Files:**
- `backend/app/services/memory/service.py:189-226`
- `backend/app/services/memory/golden_standards.py:108-116`

---

### 2. Add Token Budget to Context Injection

**Effort:** 50 lines
**Impact:** HIGH
**Priority:** Do Soon

**Problem:**
Current system returns ALL matching episodes with no limits. Risk of:
- Blowing context window
- Wasting tokens on low-relevance content
- Unpredictable injection sizes

**Solution:**

```python
# backend/app/services/memory/context_injector.py

MAX_CONTEXT_RESULTS = 50  # Hard limit
MAX_CONTENT_LENGTH = 500  # Truncate long content

class TokenBudget:
    total: int = 2000
    mandates: int = 500    # Reserved for always-inject
    guardrails: int = 300  # Reserved for anti-patterns
    reference: int = 1200  # Remaining for relevance-based

def fit_to_budget(items: list[Episode], max_tokens: int) -> list[Episode]:
    """Greedily fit items into token budget, truncating if needed."""
    result = []
    used = 0
    for item in items:
        item_tokens = count_tokens(item.content)
        if used + item_tokens <= max_tokens:
            result.append(item)
            used += item_tokens
        elif used < max_tokens:
            # Truncate last item to fit
            truncated = truncate_content(item, max_tokens - used)
            result.append(truncated)
            break
    return result
```

**Reference:**
Auto-Claude uses `MAX_CONTEXT_RESULTS = 10` and truncates content to 500 chars:
- `references/Auto-Claude/apps/backend/integrations/graphiti/queries_pkg/schema.py:17`
- `references/Auto-Claude/apps/backend/agents/memory_manager.py:182`

**Files:**
- `backend/app/services/memory/context_injector.py`
- `backend/app/services/memory/service.py:228-275` (search method)

---

### 3. Add Typed `EpisodeType` Enum

**Effort:** 100 lines
**Impact:** Medium
**Priority:** Do Later

**Problem:**
Currently infers episode type from string parsing:

```python
# service.py:687-739 - fragile string matching
if "golden_standard" in source_description:
    ...
if "gotcha" in combined or "pitfall" in combined:
    ...
```

**Solution:**

```python
# backend/app/services/memory/types.py

class EpisodeType(str, Enum):
    MANDATE = "mandate"        # Always inject, immutable rules
    GUARDRAIL = "guardrail"    # Anti-patterns, what NOT to do
    PATTERN = "pattern"        # Best practices, what TO do
    DISCOVERY = "discovery"    # Codebase findings
    GOTCHA = "gotcha"          # Pitfalls encountered
    SESSION = "session"        # Conversation learnings
    TASK = "task"              # Task-specific context (ephemeral)

class InjectionTier(str, Enum):
    ALWAYS = "always"          # Always inject (mandates)
    HIGH = "high"              # Inject if remotely relevant
    MEDIUM = "medium"          # Inject if clearly relevant
    LOW = "low"                # Inject only if highly relevant
    NEVER = "never"            # Archived, don't inject
```

Store type explicitly in episode, not inferred from strings.

**Reference:**
Auto-Claude uses explicit episode type constants:
- `references/Auto-Claude/apps/backend/integrations/graphiti/queries_pkg/schema.py:8-14`

**Files:**
- `backend/app/services/memory/service.py` (new types)
- `backend/app/services/memory/golden_standards.py` (update to use types)

---

### 4. Unify Validation Across All Entry Points

**Effort:** 150 lines
**Impact:** HIGH
**Priority:** Do Soon

**Problem:**
Validation is inconsistent:

| Entry Point | Validates Content | Checks Duplicates |
|-------------|-------------------|-------------------|
| `/api/memory/save-learning` | ✓ 3-stage | ✓ |
| `/api/memory/golden-standards` | ✓ via service | ✓ |
| `/api/memory/add` | ✗ | ✗ |
| Stream paths (2) | ✗ | ✗ |
| Completion service | ✗ | ✗ |
| Tools (3) | ✗ | ✗ |
| Consolidation (4) | ✗ | ✗ |

**Solution:**
Create `EpisodeCreator` class that ALL paths use:

```python
# backend/app/services/memory/episode_creator.py

@dataclass
class IngestionConfig:
    validate: bool = True
    deduplicate: bool = True
    dedup_window_minutes: int = 5
    tier: InjectionTier = InjectionTier.MEDIUM

# Predefined configs
GOLDEN_STANDARD = IngestionConfig(validate=True, deduplicate=True, tier=InjectionTier.ALWAYS)
CHAT_STREAM = IngestionConfig(validate=False, deduplicate=True, dedup_window_minutes=1)
LEARNING = IngestionConfig(validate=True, deduplicate=True, tier=InjectionTier.MEDIUM)

class EpisodeCreator:
    async def create(
        self,
        content: str,
        source: MemorySource,
        source_description: str,
        config: IngestionConfig = IngestionConfig(),
    ) -> CreateResult:
        # 1. Validate (if enabled)
        if config.validate:
            validation = self.validate_content(content)
            if not validation.valid:
                return CreateResult(success=False, reason=validation.reason)

        # 2. Deduplicate (if enabled)
        if config.deduplicate:
            existing = await self.find_duplicate(content, config.dedup_window_minutes)
            if existing:
                return CreateResult(success=True, uuid=existing.uuid, deduplicated=True)

        # 3. Store via MemoryService
        uuid = await self.service.add_episode(content, source, source_description)
        return CreateResult(success=True, uuid=uuid)
```

**Reference:**
Gemini Pro consultation recommended config pattern over boolean flags.

**Files:**
- NEW: `backend/app/services/memory/episode_creator.py`
- Update all 15 callers to use `EpisodeCreator`

---

### 5. Add Content Hash Deduplication

**Effort:** 50 lines
**Impact:** Medium
**Priority:** Do Soon

**Problem:**
Only `/save-learning` and golden standards check for duplicates. Other paths can create duplicates freely. Currently have 1 duplicate pair (CF Access WebSocket episodes).

**Solution:**

```python
# backend/app/services/memory/dedup.py

import hashlib

def content_hash(content: str) -> str:
    """Generate SHA-256 hash of normalized content."""
    normalized = content.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]

async def find_exact_duplicate(
    content: str,
    group_id: str,
    window_minutes: int = 5,
) -> Episode | None:
    """Find exact content match within time window."""
    hash = content_hash(content)
    cutoff = utc_now() - timedelta(minutes=window_minutes)

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.content_hash = $hash
      AND e.created_at > datetime($cutoff)
    RETURN e
    LIMIT 1
    """
    # ... execute query
```

Add `content_hash` field to episodes on creation.

**Reference:**
Auto-Claude uses set-based dedup for patterns/gotchas:
- `references/Auto-Claude/apps/backend/memory/patterns.py` (line ~15-25)

**Files:**
- NEW: `backend/app/services/memory/dedup.py`
- `backend/app/services/memory/service.py` (add hash on create)

---

### 6. Delete Garbage Episodes

**Effort:** 5 minutes
**Impact:** Low
**Priority:** Do Now

**Problem:**
2 episodes should be deleted:
1. Debug episode: `a4450f48-07cb-4545-a8bc-f37e5c219ddb` (content: "DEBUG_TRACE_1768935200...")
2. Duplicate CF Access: `0231ae50-c9f6-4d2f-8538-7c0c192963d8` (keep `b1688916-...`)

**Solution:**

```bash
cd ~/agent-hub/backend && source .venv/bin/activate

# Delete debug episode
python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password'))
s = d.session()
s.run('MATCH (e:Episodic {uuid: \"a4450f48-07cb-4545-a8bc-f37e5c219ddb\"}) DETACH DELETE e')
s.run('MATCH (e:Episodic {uuid: \"0231ae50-c9f6-4d2f-8538-7c0c192963d8\"}) DETACH DELETE e')
print('Deleted 2 episodes')
d.close()
"
```

**Files:**
- N/A (data cleanup only)

---

### 7. Add Fallback File Storage

**Effort:** 200 lines
**Impact:** Medium
**Priority:** Do Later

**Problem:**
If Neo4j is down, episodes are lost silently. No fallback.

**Solution:**

```python
# backend/app/services/memory/dual_storage.py

class DualStorage:
    def __init__(self, file_dir: Path, graphiti: Graphiti):
        self.file_dir = file_dir
        self.graphiti = graphiti
        self.retry_queue = asyncio.Queue()

    async def store(self, episode: Episode) -> str:
        # Always write to durable file storage first
        file_path = self.file_dir / f"{episode.uuid}.json"
        file_path.write_text(episode.model_dump_json())

        # Then try graph storage
        try:
            result = await self.graphiti.add_episode(...)
            # Mark as synced
            (self.file_dir / f"{episode.uuid}.synced").touch()
            return result.episode.uuid
        except Exception as e:
            logger.warning(f"Graphiti failed, queued for retry: {e}")
            await self.retry_queue.put(episode.uuid)
            return episode.uuid  # Still return success

    async def retry_pending(self):
        """Background task to retry failed syncs."""
        while True:
            uuid = await self.retry_queue.get()
            # ... retry logic
```

**Reference:**
Auto-Claude's dual-layer approach:
- `references/Auto-Claude/apps/backend/agents/memory_manager.py:242-429`
- Primary: Graphiti, Fallback: File-based (always succeeds)

**Files:**
- NEW: `backend/app/services/memory/dual_storage.py`
- Update `service.py` to use dual storage

---

### 8. Add Semantic Deduplication

**Effort:** 300 lines
**Impact:** Medium
**Priority:** Do Later

**Problem:**
Hash dedup catches exact matches. Semantic dedup catches rephrasings:
- "Always use async for I/O"
- "I/O operations must be async"
- "Never use sync methods for I/O"

All say the same thing but have different hashes.

**Solution:**

```python
# backend/app/services/memory/semantic_dedup.py

async def find_semantic_duplicate(
    content: str,
    group_id: str,
    threshold: float = 0.95,
) -> tuple[Episode | None, float]:
    """Find semantically similar episode using embeddings."""

    # Get embedding for new content
    embedding = await get_embedding(content)

    # Search for similar
    similar = await graphiti.search(
        query=content,
        group_ids=[group_id],
        num_results=5,
    )

    for candidate in similar:
        similarity = cosine_similarity(embedding, candidate.embedding)
        if similarity >= threshold:
            return candidate, similarity

    return None, 0.0
```

**Reference:**
Gemini Pro recommended hybrid approach:
1. Hash check (fast, exact)
2. Embedding similarity >0.95 (slower, semantic)
3. Time delta check (same day = merge, different day = new episode)

**Files:**
- NEW: `backend/app/services/memory/semantic_dedup.py`
- `backend/app/services/memory/episode_creator.py` (integrate)

---

### 9. Implement Utility Scoring + Decay

**Effort:** 400 lines
**Impact:** Medium
**Priority:** Do Later

**Problem:**
All episodes are equal forever. Frequently-cited episodes should rank higher. Unused episodes should fade.

**Solution:**

```python
# backend/app/services/memory/utility.py

class UtilityTracker:
    async def on_episode_loaded(self, uuid: str):
        """Episode was included in context injection."""
        await self._increment(uuid, "loaded_count")

    async def on_episode_cited(self, uuid: str):
        """User explicitly referenced this episode (e.g., [M:uuid])."""
        await self._increment(uuid, "cited_count")
        await self._boost_utility(uuid, 0.1)

    async def on_task_success(self, loaded_uuids: list[str]):
        """Task succeeded - boost all loaded episodes slightly."""
        for uuid in loaded_uuids:
            await self._boost_utility(uuid, 0.02)

    async def on_task_failure(self, loaded_uuids: list[str]):
        """Task failed - slightly penalize loaded episodes."""
        for uuid in loaded_uuids:
            await self._decay_utility(uuid, 0.01)

    async def periodic_decay(self):
        """Run daily - unused episodes fade."""
        query = """
        MATCH (e:Episodic)
        WHERE e.last_accessed_at < datetime() - duration('P30D')
          AND NOT e.source_description CONTAINS 'golden_standard'
        SET e.utility_score = e.utility_score * 0.9
        """
        # Mandates are immune to decay
```

**Files:**
- NEW: `backend/app/services/memory/utility.py`
- `backend/app/services/memory/context_injector.py` (track loads)
- `backend/app/api/memory.py` (track citations)

---

### 10. Add Atomic Distillation (SPO Extraction)

**Effort:** 500 lines
**Impact:** HIGH (but complex)
**Priority:** Do Later (v2)

**Problem:**
Store raw content, hope Graphiti extracts entities. No control over what facts are stored.

**Solution:**
Extract Subject-Predicate-Object tuples at write time:

```python
# backend/app/services/memory/atoms.py

class Atom(BaseModel):
    subject: str
    predicate: str
    object: str
    negated: bool = False

async def extract_atoms(content: str) -> list[Atom]:
    """Use LLM to extract atomic facts from content."""
    prompt = """
    Extract distinct facts as subject-predicate-object tuples.
    For negations, set negated=true.

    Content: {content}

    Output JSON array of: {{"subject": "...", "predicate": "...", "object": "...", "negated": false}}
    """

    response = await llm.complete(prompt.format(content=content))
    return [Atom(**a) for a in json.loads(response)]

# Example:
# Content: "Claude uses OAuth, NOT API keys."
# Atoms:
#   - Atom(subject="Claude", predicate="uses", object="OAuth", negated=False)
#   - Atom(subject="Claude", predicate="uses", object="API keys", negated=True)
```

Benefits:
- Precise deduplication (atoms match regardless of phrasing)
- Contradiction detection
- Token-efficient injection (inject atoms, not prose)

**Files:**
- NEW: `backend/app/services/memory/atoms.py`
- Update episode model to include `atoms: list[Atom]`

---

### 11. Build Promotion Pipeline

**Effort:** 300 lines
**Impact:** Low
**Priority:** Do Later

**Problem:**
Episodes stay at initial tier forever. No automatic promotion based on evidence.

**Solution:**

```
PROVISIONAL (70-89% confidence)
    │
    │ Cited 3+ times, no contradictions
    ▼
CANONICAL (90-99% confidence)
    │
    │ Cited 10+ times, verified by human/opus
    ▼
MANDATE (100% confidence, always inject)
```

```python
# backend/app/services/memory/promotion.py

class PromotionEngine:
    async def check_for_promotion(self, uuid: str):
        episode = await self.get(uuid)
        stats = await self.get_stats(uuid)

        if episode.tier == Tier.PROVISIONAL:
            if stats.cited_count >= 3 and stats.contradiction_count == 0:
                await self.promote(uuid, Tier.CANONICAL)
                logger.info(f"Promoted {uuid} to CANONICAL")

        elif episode.tier == Tier.CANONICAL:
            if stats.cited_count >= 10:
                await self.queue_for_verification(uuid)
```

**Files:**
- NEW: `backend/app/services/memory/promotion.py`
- Background task to run periodically

---

### 12. Add Contradiction Detection

**Effort:** 400 lines
**Impact:** Low (at current scale)
**Priority:** Do Later

**Problem:**
System happily stores contradictory facts:
- Episode A: "Always use PostgreSQL for user data"
- Episode B: "Never use PostgreSQL for user data"

Both get injected, confusing the model.

**Solution:**

```python
# backend/app/services/memory/contradictions.py

class ContradictionDetector:
    async def check(self, new_episode: Episode) -> ContradictionResult:
        # Requires atoms (recommendation #10)
        for new_atom in new_episode.atoms:
            # Find existing atoms with same subject+predicate
            existing = await self.find_matching_atoms(
                new_atom.subject,
                new_atom.predicate
            )

            for old_atom in existing:
                if self.contradicts(new_atom, old_atom):
                    return ContradictionResult(
                        found=True,
                        new_atom=new_atom,
                        existing_atom=old_atom,
                        existing_episode=old_atom.episode_uuid,
                    )

        return ContradictionResult(found=False)

    def contradicts(self, a: Atom, b: Atom) -> bool:
        """Same subject+predicate but different object or negation."""
        if a.subject != b.subject or a.predicate != b.predicate:
            return False
        return a.object != b.object or a.negated != b.negated
```

**Files:**
- NEW: `backend/app/services/memory/contradictions.py`
- Depends on recommendation #10 (atoms)

---

## Reference: Auto-Claude Patterns

**Repository:** `~/summitflow/references/Auto-Claude`

### Key Files

| File | Purpose |
|------|---------|
| `apps/backend/agents/memory_manager.py` | Dual-layer storage (Graphiti + file fallback) |
| `apps/backend/integrations/graphiti/queries_pkg/schema.py` | Episode types, MAX_CONTEXT_RESULTS |
| `apps/backend/integrations/graphiti/queries_pkg/queries.py` | Episode operations |
| `apps/backend/memory/patterns.py` | Set-based deduplication |

### Key Patterns

1. **Primary/Fallback Guarantee**: Always write to file first, then sync to Graphiti
2. **Typed Episodes**: Explicit `EPISODE_TYPE_*` constants
3. **Token Control**: `MAX_CONTEXT_RESULTS = 10`, truncation to 500 chars
4. **Group ID Modes**: `SPEC` (isolated) vs `PROJECT` (shared)

---

## Reference: Gemini Pro Consultation

**Date:** 2026-01-23
**Query:** Memory system architecture review

### Key Recommendations

1. **Single funnel with config objects** - Don't use boolean flags, use `IngestionConfig` strategy objects
2. **Hybrid deduplication**:
   - Step 1: SHA-256 hash for exact match within 5-min window
   - Step 2: Embedding similarity >0.95 with time delta check
3. **Fix orphans immediately** - 32 is trivial, archive unrecoverable
4. **Distillation over truncation** - Extract SPO tuples at write time

### Full Response

> "This is a classic 'spaghetti to lasagna' architectural refactor. Moving from 17 scattered entry points to a unified EpisodeCreator is absolutely the right move."

---

## File References

### Agent Hub Memory System

| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/memory/service.py` | 951 | Core MemoryService class |
| `backend/app/services/memory/golden_standards.py` | 400 | Golden standard storage (bypasses service) |
| `backend/app/services/memory/context_injector.py` | ~300 | Context building for injection |
| `backend/app/services/memory/tools.py` | 322 | Agent tools (discovery, gotcha, pattern) |
| `backend/app/services/memory/learning_extractor.py` | ~300 | LLM-based learning extraction |
| `backend/app/services/memory/consolidation.py` | ~270 | Task memory promotion |
| `backend/app/api/memory.py` | ~1000 | REST API endpoints |
| `backend/app/api/stream.py` | ~820 | WebSocket streaming (stores episodes) |
| `backend/app/services/completion.py` | ~350 | Completion service (stores episodes) |

### Scripts

| File | Purpose |
|------|---------|
| `backend/scripts/memory/audit_episodes.py` | Episode quality audit |
| `backend/scripts/memory/cleanup_legacy.py` | Legacy group cleanup |
| `backend/scripts/memory/consolidate_duplicates.py` | Duplicate entity consolidation |
| `backend/scripts/memory/backup.py` | Memory backup |
| `backend/scripts/memory/inventory.py` | Memory inventory |

---

## Summary

| Priority | Items | Total Effort |
|----------|-------|--------------|
| **Do Now** | #1 (DRY fix), #6 (delete garbage) | 15 min |
| **Do Soon** | #2 (token budget), #4 (validation), #5 (hash dedup) | 250 lines |
| **Do Later** | #3, #7, #8, #9 | 1000 lines |
| **v2** | #10, #11, #12 | 1200 lines |

**Recommended Immediate Action:** Items 1, 2, 5, 6 (~80 lines + cleanup)
