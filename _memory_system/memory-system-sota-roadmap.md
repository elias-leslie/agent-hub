# Memory System SOTA Roadmap

**Date:** 2026-01-23
**Vision:** Transform Agent Hub's memory system into a state-of-the-art agentic memory pipeline
**Approach:** Incremental phases, each delivering value independently

---

## The Vision

### Current State
```
Raw Input → Store in Graphiti → Retrieve → Inject
```

### SOTA Target
```
Raw Input → Validate → Distill → Dedupe → Store → Decay → Retrieve → Budget → Assemble → Inject
     ↑                                        ↓
     └──────────── Feedback Loop ─────────────┘
                (utility scoring, promotion)
```

---

## Phase Overview

| Phase | Name | Effort | Cumulative Value |
|-------|------|--------|------------------|
| 0 | Quick Wins | 1 day | Fix immediate issues |
| 1 | Single Funnel | 3 days | Consistent write path |
| 2 | Token Efficiency | 2 days | Controlled context size |
| 3 | Data Quality | 3 days | Clean, deduplicated data |
| 4 | Observability | 2 days | Metrics and debugging |
| 5 | Lifecycle Management | 5 days | Utility scoring, decay |
| 6 | Intelligence Layer | 10 days | Atoms, contradictions |

**Total:** ~26 days to full SOTA (can stop at any phase)

---

## Phase 0: Quick Wins (Day 1)

**Goal:** Fix immediate issues without architectural changes

### Tasks

1. **Fix DRY violation** (10 lines)
   ```python
   # service.py - add name parameter
   async def add_episode(
       self,
       content: str,
       source: MemorySource = MemorySource.CHAT,
       source_description: str | None = None,
       reference_time: datetime | None = None,
       name: str | None = None,  # NEW
   ) -> str:
       name = name or f"{source.value}_{reference_time.isoformat()}"
   ```

2. **Delete garbage episodes** (5 min)
   ```python
   # Delete debug + duplicate
   DELETE_UUIDS = [
       "a4450f48-07cb-4545-a8bc-f37e5c219ddb",  # DEBUG_TRACE
       "0231ae50-c9f6-4d2f-8538-7c0c192963d8",  # Duplicate CF Access
   ]
   ```

3. **Update golden_standards to use service** (20 lines)
   ```python
   # golden_standards.py - call through service
   service = get_memory_service(scope, scope_id)
   new_uuid = await service.add_episode(
       content=episode.episode_body,
       source=MemorySource.SYSTEM,
       source_description=episode.source_description,
       name=episode.name,
   )
   ```

### Deliverables
- [ ] Single Graphiti call site (MemoryService only)
- [ ] 184 clean episodes (down from 186)

### Verification
```bash
# Should return 1 (only service.py)
rg "graphiti\.add_episode|_graphiti\.add_episode" backend/app --files-with-matches | wc -l
```

---

## Phase 1: Single Funnel (Days 2-4)

**Goal:** All episode creation goes through one class with configurable behavior

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     EpisodeCreator                          │
│                                                             │
│  create(content, source, config: IngestionConfig)           │
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │Validate │→ │ Dedupe  │→ │ Format  │→ │  Store  │        │
│  │(optional)│  │(optional)│  │         │  │         │        │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### New Files

**`backend/app/services/memory/types.py`**
```python
from enum import Enum
from pydantic import BaseModel

class EpisodeType(str, Enum):
    MANDATE = "mandate"
    GUARDRAIL = "guardrail"
    PATTERN = "pattern"
    DISCOVERY = "discovery"
    GOTCHA = "gotcha"
    SESSION = "session"
    TASK = "task"

class InjectionTier(str, Enum):
    ALWAYS = "always"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEVER = "never"

class EpisodeStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"
    SUPERSEDED = "superseded"
```

**`backend/app/services/memory/ingestion_config.py`**
```python
from dataclasses import dataclass

@dataclass
class IngestionConfig:
    validate: bool = True
    deduplicate: bool = True
    dedup_window_minutes: int = 5
    episode_type: EpisodeType = EpisodeType.SESSION
    tier: InjectionTier = InjectionTier.MEDIUM
    max_content_length: int | None = None

# Predefined configs
GOLDEN_STANDARD = IngestionConfig(
    validate=True,
    deduplicate=True,
    episode_type=EpisodeType.MANDATE,
    tier=InjectionTier.ALWAYS,
)

CHAT_STREAM = IngestionConfig(
    validate=False,
    deduplicate=True,
    dedup_window_minutes=1,
    episode_type=EpisodeType.SESSION,
    tier=InjectionTier.LOW,
)

LEARNING = IngestionConfig(
    validate=True,
    deduplicate=True,
    episode_type=EpisodeType.PATTERN,
    tier=InjectionTier.MEDIUM,
)

TOOL_DISCOVERY = IngestionConfig(
    validate=False,
    deduplicate=True,
    episode_type=EpisodeType.DISCOVERY,
    tier=InjectionTier.MEDIUM,
)

TOOL_GOTCHA = IngestionConfig(
    validate=False,
    deduplicate=True,
    episode_type=EpisodeType.GOTCHA,
    tier=InjectionTier.HIGH,
)
```

**`backend/app/services/memory/episode_creator.py`**
```python
from dataclasses import dataclass
from .types import EpisodeType, InjectionTier
from .ingestion_config import IngestionConfig
from .service import MemoryService, MemorySource, get_memory_service

@dataclass
class CreateResult:
    success: bool
    uuid: str | None = None
    deduplicated: bool = False
    validation_error: str | None = None

class EpisodeCreator:
    def __init__(self, service: MemoryService):
        self.service = service

    async def create(
        self,
        content: str,
        source: MemorySource,
        source_description: str,
        config: IngestionConfig,
        name: str | None = None,
    ) -> CreateResult:
        # 1. Validate (if enabled)
        if config.validate:
            error = self._validate_content(content)
            if error:
                return CreateResult(success=False, validation_error=error)

        # 2. Truncate (if configured)
        if config.max_content_length and len(content) > config.max_content_length:
            content = content[:config.max_content_length] + "..."

        # 3. Deduplicate (if enabled)
        if config.deduplicate:
            existing = await self._find_duplicate(content, config.dedup_window_minutes)
            if existing:
                return CreateResult(success=True, uuid=existing, deduplicated=True)

        # 4. Enrich source_description with type/tier
        enriched_desc = self._enrich_description(
            source_description,
            config.episode_type,
            config.tier,
        )

        # 5. Store
        uuid = await self.service.add_episode(
            content=content,
            source=source,
            source_description=enriched_desc,
            name=name,
        )

        return CreateResult(success=True, uuid=uuid)

    def _validate_content(self, content: str) -> str | None:
        """Return error message if invalid, None if valid."""
        if len(content) < 10:
            return "Content too short"
        if len(content) > 50000:
            return "Content too long"
        # Add more validation as needed
        return None

    async def _find_duplicate(self, content: str, window_minutes: int) -> str | None:
        """Return UUID of duplicate if found, None otherwise."""
        # Phase 3 will implement this
        return None

    def _enrich_description(
        self,
        desc: str,
        episode_type: EpisodeType,
        tier: InjectionTier,
    ) -> str:
        """Add type and tier to source description for filtering."""
        return f"{desc} type:{episode_type.value} tier:{tier.value}"


def get_episode_creator(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> EpisodeCreator:
    """Factory function for EpisodeCreator."""
    service = get_memory_service(scope, scope_id)
    return EpisodeCreator(service)
```

### Migration Tasks

Update all 15 callers to use `EpisodeCreator`:

| File | Current | New |
|------|---------|-----|
| `api/memory.py:130` | `memory.add_episode(...)` | `creator.create(..., LEARNING)` |
| `api/memory.py:1006` | `service.add_episode(...)` | `creator.create(..., LEARNING)` |
| `api/stream.py:686` | `memory_service.add_episode(...)` | `creator.create(..., CHAT_STREAM)` |
| `api/stream.py:816` | `memory_service.add_episode(...)` | `creator.create(..., CHAT_STREAM)` |
| `services/completion.py:337` | `memory_service.add_episode(...)` | `creator.create(..., CHAT_STREAM)` |
| `services/orchestration/roundtable.py:615` | `service.add_episode(...)` | `creator.create(..., SESSION)` |
| `services/memory/learning_extractor.py:254` | `service.add_episode(...)` | `creator.create(..., LEARNING)` |
| `services/memory/golden_standards.py` | Direct Graphiti | `creator.create(..., GOLDEN_STANDARD)` |
| `services/memory/consolidation.py` (4x) | `project_service.add_episode(...)` | `creator.create(..., LEARNING)` |
| `services/memory/tools.py` (3x) | `service.add_episode(...)` | `creator.create(..., TOOL_*)` |

### Deliverables
- [ ] `EpisodeCreator` class with configurable behavior
- [ ] `IngestionConfig` with predefined profiles
- [ ] All callers migrated
- [ ] Type/tier stored in source_description

### Verification
```bash
# All episode creation should go through EpisodeCreator
rg "\.add_episode\(" backend/app --type py | grep -v "episode_creator.py" | grep -v "test_"
# Should only show the one call inside EpisodeCreator
```

---

## Phase 2: Token Efficiency (Days 5-6)

**Goal:** Control context injection size, prevent token waste

### New Constants

**`backend/app/services/memory/constants.py`**
```python
# Retrieval limits
MAX_CONTEXT_RESULTS = 50
MAX_MANDATES = 20
MAX_GUARDRAILS = 15
MAX_REFERENCE = 30

# Content limits
MAX_CONTENT_LENGTH = 2000  # Truncate on retrieval
MAX_ATOM_LENGTH = 200

# Token budgets
class TokenBudget:
    TOTAL = 2000
    MANDATES = 500      # Reserved for always-inject
    GUARDRAILS = 300    # Reserved for anti-patterns
    REFERENCE = 1200    # Remaining for relevance-based
```

### Updated Context Builder

**`backend/app/services/memory/context_injector.py`** (updates)
```python
from .constants import TokenBudget, MAX_CONTENT_LENGTH

class ProgressiveContext:
    def __init__(self):
        self.mandates: list[Episode] = []
        self.guardrails: list[Episode] = []
        self.reference: list[Episode] = []
        self._token_count = 0

    def token_count(self) -> int:
        return self._token_count

    def add_mandate(self, episode: Episode, tokens: int):
        self.mandates.append(episode)
        self._token_count += tokens

    def add_guardrail(self, episode: Episode, tokens: int):
        self.guardrails.append(episode)
        self._token_count += tokens

    def add_reference(self, episode: Episode, tokens: int):
        self.reference.append(episode)
        self._token_count += tokens


async def build_progressive_context(
    query: str,
    budget: TokenBudget = TokenBudget(),
) -> ProgressiveContext:
    context = ProgressiveContext()

    # 1. Mandates ALWAYS included (up to budget)
    mandates = await get_mandates()
    for m in mandates:
        tokens = count_tokens(m.content)
        if context.token_count() + tokens <= budget.MANDATES:
            context.add_mandate(truncate(m, MAX_CONTENT_LENGTH), tokens)

    # 2. Guardrails by relevance
    guardrails = await search_guardrails(query)
    for g in guardrails:
        tokens = count_tokens(g.content)
        if context.token_count() + tokens <= budget.MANDATES + budget.GUARDRAILS:
            context.add_guardrail(truncate(g, MAX_CONTENT_LENGTH), tokens)

    # 3. Reference fills remaining
    remaining = budget.TOTAL - context.token_count()
    reference = await search_reference(query)
    for r in reference:
        tokens = count_tokens(r.content)
        if tokens <= remaining:
            context.add_reference(truncate(r, MAX_CONTENT_LENGTH), tokens)
            remaining -= tokens

    return context


def truncate(episode: Episode, max_length: int) -> Episode:
    """Truncate content if too long."""
    if len(episode.content) <= max_length:
        return episode
    return episode.model_copy(
        update={"content": episode.content[:max_length] + "..."}
    )


def count_tokens(text: str) -> int:
    """Estimate token count (rough: 4 chars per token)."""
    return len(text) // 4
```

### Deliverables
- [ ] Token budget enforcement
- [ ] Content truncation on retrieval
- [ ] Result count limits

### Verification
```python
# Context should never exceed budget
context = await build_progressive_context("test query")
assert context.token_count() <= TokenBudget.TOTAL
```

---

## Phase 3: Data Quality (Days 7-9)

**Goal:** Prevent duplicates, ensure clean data

### Hash-Based Deduplication

**`backend/app/services/memory/dedup.py`**
```python
import hashlib
from datetime import timedelta
from graphiti_core.utils.datetime_utils import utc_now

def content_hash(content: str) -> str:
    """Generate hash of normalized content."""
    normalized = " ".join(content.lower().split())  # Normalize whitespace
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def find_exact_duplicate(
    graphiti,
    content: str,
    group_id: str,
    window_minutes: int = 5,
) -> str | None:
    """Find exact content match within time window."""
    hash_value = content_hash(content)
    cutoff = utc_now() - timedelta(minutes=window_minutes)

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.content_hash = $hash
      AND e.created_at > datetime($cutoff)
    RETURN e.uuid AS uuid
    LIMIT 1
    """

    records, _, _ = await graphiti.driver.execute_query(
        query,
        group_id=group_id,
        hash=hash_value,
        cutoff=cutoff.isoformat(),
    )

    return records[0]["uuid"] if records else None


async def add_content_hash_to_episode(graphiti, uuid: str, content: str):
    """Add content_hash to existing episode."""
    hash_value = content_hash(content)

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.content_hash = $hash
    """

    await graphiti.driver.execute_query(query, uuid=uuid, hash=hash_value)
```

### Update EpisodeCreator

```python
# In episode_creator.py

async def _find_duplicate(self, content: str, window_minutes: int) -> str | None:
    """Return UUID of duplicate if found."""
    from .dedup import find_exact_duplicate

    return await find_exact_duplicate(
        self.service._graphiti,
        content,
        self.service._group_id,
        window_minutes,
    )
```

### Migration Script

**`backend/scripts/memory/add_content_hashes.py`**
```python
"""Add content_hash to all existing episodes."""

async def migrate():
    graphiti = get_graphiti()

    # Get all episodes without hash
    query = """
    MATCH (e:Episodic)
    WHERE e.content_hash IS NULL
    RETURN e.uuid AS uuid, e.content AS content
    """

    records, _, _ = await graphiti.driver.execute_query(query)

    for record in records:
        hash_value = content_hash(record["content"])
        await graphiti.driver.execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) SET e.content_hash = $hash",
            uuid=record["uuid"],
            hash=hash_value,
        )

    print(f"Added hashes to {len(records)} episodes")
```

### Deliverables
- [ ] `content_hash` field on all episodes
- [ ] Hash-based exact deduplication
- [ ] Migration script for existing data

### Verification
```python
# Creating same content twice should deduplicate
result1 = await creator.create("Test content", ...)
result2 = await creator.create("Test content", ...)
assert result2.deduplicated == True
assert result1.uuid == result2.uuid
```

---

## Phase 4: Observability (Days 10-11)

**Goal:** Metrics, logging, debugging tools

### Metrics

**`backend/app/services/memory/metrics.py`**
```python
from prometheus_client import Counter, Histogram, Gauge

# Write metrics
EPISODES_CREATED = Counter(
    "memory_episodes_created_total",
    "Total episodes created",
    ["type", "tier", "scope"]
)
EPISODES_DEDUPLICATED = Counter(
    "memory_episodes_deduplicated_total",
    "Episodes deduplicated (not created)"
)
EPISODES_REJECTED = Counter(
    "memory_episodes_rejected_total",
    "Episodes rejected by validation",
    ["reason"]
)

# Read metrics
CONTEXT_INJECTIONS = Counter(
    "memory_context_injections_total",
    "Total context injection requests"
)
TOKENS_INJECTED = Histogram(
    "memory_tokens_injected",
    "Tokens injected per request",
    buckets=[100, 500, 1000, 1500, 2000, 3000, 5000]
)
RETRIEVAL_LATENCY = Histogram(
    "memory_retrieval_latency_seconds",
    "Context retrieval latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# Quality metrics
ORPHAN_EPISODES = Gauge(
    "memory_orphan_episodes",
    "Episodes with no entity edges"
)
DUPLICATE_EPISODES = Gauge(
    "memory_duplicate_episodes",
    "Episodes with duplicate content"
)
EPISODE_COUNT = Gauge(
    "memory_episode_count",
    "Total episode count",
    ["scope", "type"]
)
```

### Integrate Metrics

```python
# In episode_creator.py

async def create(self, content, source, source_description, config, name=None):
    # ... validation ...
    if error:
        EPISODES_REJECTED.labels(reason=error).inc()
        return CreateResult(success=False, validation_error=error)

    # ... deduplication ...
    if existing:
        EPISODES_DEDUPLICATED.inc()
        return CreateResult(success=True, uuid=existing, deduplicated=True)

    # ... store ...
    uuid = await self.service.add_episode(...)
    EPISODES_CREATED.labels(
        type=config.episode_type.value,
        tier=config.tier.value,
        scope=self.service.scope.value,
    ).inc()

    return CreateResult(success=True, uuid=uuid)
```

### Health Check Script

**`backend/scripts/memory/health_check.py`**
```python
"""Memory system health check."""

async def check_health():
    graphiti = get_graphiti()
    driver = graphiti.driver

    issues = []

    # Check for orphans
    orphans = await driver.execute_query("""
        MATCH (e:Episodic)
        WHERE e.entity_edges IS NULL OR size(e.entity_edges) = 0
        RETURN count(e) AS count
    """)
    orphan_count = orphans[0][0]["count"]
    if orphan_count > 50:
        issues.append(f"High orphan count: {orphan_count}")

    # Check for duplicates
    dupes = await driver.execute_query("""
        MATCH (e:Episodic)
        WITH e.content_hash AS hash, count(*) AS cnt
        WHERE cnt > 1
        RETURN sum(cnt - 1) AS duplicates
    """)
    dupe_count = dupes[0][0]["duplicates"] or 0
    if dupe_count > 0:
        issues.append(f"Duplicate episodes: {dupe_count}")

    # Check for missing hashes
    no_hash = await driver.execute_query("""
        MATCH (e:Episodic)
        WHERE e.content_hash IS NULL
        RETURN count(e) AS count
    """)
    no_hash_count = no_hash[0][0]["count"]
    if no_hash_count > 0:
        issues.append(f"Episodes without hash: {no_hash_count}")

    if issues:
        print("UNHEALTHY:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("HEALTHY")
        return True
```

### Deliverables
- [ ] Prometheus metrics
- [ ] Health check script
- [ ] Dashboard queries

---

## Phase 5: Lifecycle Management (Days 12-16)

**Goal:** Utility scoring, decay, promotion

### Utility Tracker

**`backend/app/services/memory/utility.py`**
```python
from datetime import timedelta
from graphiti_core.utils.datetime_utils import utc_now

class UtilityTracker:
    def __init__(self, graphiti):
        self.graphiti = graphiti
        self.driver = graphiti.driver

    async def on_episode_loaded(self, uuids: list[str]):
        """Episodes included in context injection."""
        if not uuids:
            return

        now = utc_now().isoformat()
        await self.driver.execute_query("""
            UNWIND $uuids AS uuid
            MATCH (e:Episodic {uuid: uuid})
            SET e.loaded_count = COALESCE(e.loaded_count, 0) + 1,
                e.last_accessed_at = datetime($now)
        """, uuids=uuids, now=now)

    async def on_episode_cited(self, uuid: str):
        """User explicitly referenced episode (e.g., [M:uuid])."""
        await self.driver.execute_query("""
            MATCH (e:Episodic {uuid: $uuid})
            SET e.cited_count = COALESCE(e.cited_count, 0) + 1,
                e.utility_score = COALESCE(e.utility_score, 0.5) + 0.1,
                e.last_accessed_at = datetime($now)
        """, uuid=uuid, now=utc_now().isoformat())

    async def on_task_success(self, loaded_uuids: list[str]):
        """Task succeeded - boost loaded episodes."""
        if not loaded_uuids:
            return

        await self.driver.execute_query("""
            UNWIND $uuids AS uuid
            MATCH (e:Episodic {uuid: uuid})
            SET e.success_count = COALESCE(e.success_count, 0) + 1,
                e.utility_score = COALESCE(e.utility_score, 0.5) + 0.02
        """, uuids=loaded_uuids)

    async def on_task_failure(self, loaded_uuids: list[str]):
        """Task failed - slight penalty to loaded episodes."""
        if not loaded_uuids:
            return

        await self.driver.execute_query("""
            UNWIND $uuids AS uuid
            MATCH (e:Episodic {uuid: uuid})
            SET e.failure_count = COALESCE(e.failure_count, 0) + 1,
                e.utility_score = COALESCE(e.utility_score, 0.5) - 0.01
        """, uuids=loaded_uuids)

    async def decay_unused(self, days_threshold: int = 30):
        """Decay utility for episodes not accessed recently."""
        cutoff = (utc_now() - timedelta(days=days_threshold)).isoformat()

        # Decay non-mandates that haven't been accessed
        await self.driver.execute_query("""
            MATCH (e:Episodic)
            WHERE (e.last_accessed_at IS NULL OR e.last_accessed_at < datetime($cutoff))
              AND NOT e.source_description CONTAINS 'tier:always'
              AND COALESCE(e.utility_score, 0.5) > 0.1
            SET e.utility_score = COALESCE(e.utility_score, 0.5) * 0.9
        """, cutoff=cutoff)
```

### Promotion Engine

**`backend/app/services/memory/promotion.py`**
```python
class PromotionEngine:
    def __init__(self, graphiti):
        self.graphiti = graphiti
        self.driver = graphiti.driver

    async def check_promotions(self):
        """Check and promote eligible episodes."""

        # Provisional → Canonical (cited 3+ times, no issues)
        await self.driver.execute_query("""
            MATCH (e:Episodic)
            WHERE e.source_description CONTAINS 'tier:medium'
              AND COALESCE(e.cited_count, 0) >= 3
              AND COALESCE(e.failure_count, 0) = 0
            SET e.source_description = replace(e.source_description, 'tier:medium', 'tier:high')
        """)

        # Canonical → Mandate candidate (cited 10+ times)
        candidates = await self.driver.execute_query("""
            MATCH (e:Episodic)
            WHERE e.source_description CONTAINS 'tier:high'
              AND COALESCE(e.cited_count, 0) >= 10
              AND NOT e.source_description CONTAINS 'promotion_candidate'
            SET e.source_description = e.source_description + ' promotion_candidate'
            RETURN e.uuid AS uuid, e.content AS content
        """)

        # Return candidates for human/opus review
        return [{"uuid": r["uuid"], "content": r["content"]} for r in candidates[0]]

    async def promote_to_mandate(self, uuid: str):
        """Manually promote to mandate tier."""
        await self.driver.execute_query("""
            MATCH (e:Episodic {uuid: $uuid})
            SET e.source_description = replace(e.source_description, 'tier:high', 'tier:always')
        """, uuid=uuid)
```

### Deliverables
- [ ] Utility tracking on load/cite/success/failure
- [ ] Daily decay job
- [ ] Promotion pipeline
- [ ] API endpoint to approve promotions

---

## Phase 6: Intelligence Layer (Days 17-26)

**Goal:** Atomic distillation, semantic dedup, contradiction detection

### Atom Extraction

**`backend/app/services/memory/atoms.py`**
```python
from pydantic import BaseModel

class Atom(BaseModel):
    """Smallest unit of knowledge - a single fact."""
    subject: str
    predicate: str
    object: str
    negated: bool = False

    def __hash__(self):
        return hash((self.subject, self.predicate, self.object, self.negated))

    def __eq__(self, other):
        if not isinstance(other, Atom):
            return False
        return (
            self.subject == other.subject
            and self.predicate == other.predicate
            and self.object == other.object
            and self.negated == other.negated
        )


async def extract_atoms(content: str, llm_client) -> list[Atom]:
    """Extract SPO tuples from content using LLM."""
    prompt = """Extract distinct facts from the following content as subject-predicate-object tuples.
For negations (things that should NOT be done), set negated=true.
Return valid JSON array.

Content:
{content}

Output format:
[{{"subject": "...", "predicate": "...", "object": "...", "negated": false}}]

Rules:
- Subject: The entity doing/being something
- Predicate: The relationship or action
- Object: The target or value
- Be concise - each field should be 1-5 words
- Extract ALL distinct facts, not just the main one
"""

    response = await llm_client.complete(
        model="claude-haiku-4-5",  # Cheap, fast
        messages=[{"role": "user", "content": prompt.format(content=content)}],
    )

    try:
        atoms_data = json.loads(response.content)
        return [Atom(**a) for a in atoms_data]
    except Exception:
        return []  # Graceful fallback


# Example:
# Content: "Claude uses OAuth for authentication. Never use API keys."
# Atoms:
#   - Atom(subject="Claude", predicate="uses", object="OAuth")
#   - Atom(subject="Claude", predicate="authenticates via", object="OAuth")
#   - Atom(subject="API keys", predicate="should be used", object="for Claude", negated=True)
```

### Semantic Deduplication

**`backend/app/services/memory/semantic_dedup.py`**
```python
async def find_semantic_duplicate(
    graphiti,
    content: str,
    group_id: str,
    threshold: float = 0.95,
) -> tuple[str | None, float]:
    """Find semantically similar episode."""

    # Search for similar content
    similar = await graphiti.search(
        query=content,
        group_ids=[group_id],
        num_results=5,
    )

    for candidate in similar:
        score = getattr(candidate, "score", 0.0)
        if score >= threshold:
            return candidate.uuid, score

    return None, 0.0


async def find_atom_duplicate(
    driver,
    atoms: list[Atom],
    group_id: str,
) -> str | None:
    """Find episode with matching atoms."""

    # Convert atoms to searchable format
    atom_hashes = [hash(a) for a in atoms]

    # This requires atoms stored in Neo4j
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE any(h IN $hashes WHERE h IN e.atom_hashes)
    WITH e, size([h IN $hashes WHERE h IN e.atom_hashes]) AS matches
    WHERE matches >= size($hashes) * 0.8
    RETURN e.uuid AS uuid
    ORDER BY matches DESC
    LIMIT 1
    """

    records, _, _ = await driver.execute_query(
        query,
        group_id=group_id,
        hashes=atom_hashes,
    )

    return records[0]["uuid"] if records else None
```

### Contradiction Detection

**`backend/app/services/memory/contradictions.py`**
```python
from dataclasses import dataclass

@dataclass
class Contradiction:
    new_atom: Atom
    existing_atom: Atom
    existing_episode_uuid: str
    severity: str  # "direct" or "implicit"


class ContradictionDetector:
    def __init__(self, driver):
        self.driver = driver

    async def check(self, new_atoms: list[Atom], group_id: str) -> list[Contradiction]:
        """Find contradictions between new atoms and existing knowledge."""

        contradictions = []

        for new_atom in new_atoms:
            # Find atoms with same subject+predicate
            query = """
            MATCH (e:Episodic {group_id: $group_id})
            WHERE any(a IN e.atoms WHERE
                a.subject = $subject AND a.predicate = $predicate)
            RETURN e.uuid AS uuid, e.atoms AS atoms
            """

            records, _, _ = await self.driver.execute_query(
                query,
                group_id=group_id,
                subject=new_atom.subject,
                predicate=new_atom.predicate,
            )

            for record in records:
                for existing in record["atoms"]:
                    existing_atom = Atom(**existing)

                    if self._contradicts(new_atom, existing_atom):
                        contradictions.append(Contradiction(
                            new_atom=new_atom,
                            existing_atom=existing_atom,
                            existing_episode_uuid=record["uuid"],
                            severity="direct" if new_atom.negated != existing_atom.negated else "implicit",
                        ))

        return contradictions

    def _contradicts(self, a: Atom, b: Atom) -> bool:
        """Check if atoms contradict."""
        # Same subject+predicate required
        if a.subject != b.subject or a.predicate != b.predicate:
            return False

        # Direct contradiction: same fact, different negation
        if a.object == b.object and a.negated != b.negated:
            return True

        # Implicit contradiction: different objects (might be OK)
        if a.object != b.object:
            return True  # Flag for review

        return False
```

### Integration into EpisodeCreator

```python
# In episode_creator.py (Phase 6 version)

async def create(self, content, source, source_description, config, name=None):
    # ... validation ...

    # Extract atoms (Phase 6)
    atoms = await extract_atoms(content, self.llm_client)

    # Check for contradictions (Phase 6)
    if config.check_contradictions and atoms:
        contradictions = await self.contradiction_detector.check(
            atoms, self.service._group_id
        )
        if contradictions:
            return CreateResult(
                success=False,
                validation_error="Contradicts existing knowledge",
                contradictions=contradictions,
            )

    # Semantic dedup (Phase 6)
    if config.semantic_deduplicate:
        existing, score = await find_semantic_duplicate(
            self.service._graphiti,
            content,
            self.service._group_id,
        )
        if existing:
            return CreateResult(success=True, uuid=existing, deduplicated=True)

    # ... store with atoms ...
    uuid = await self.service.add_episode(
        content=content,
        atoms=[a.model_dump() for a in atoms],  # Store atoms
        # ...
    )

    return CreateResult(success=True, uuid=uuid)
```

### Deliverables
- [ ] Atom extraction via LLM
- [ ] Atoms stored with episodes
- [ ] Semantic deduplication
- [ ] Contradiction detection
- [ ] API for contradiction resolution

---

## Summary: Incremental Value Delivery

| Phase | Days | Cumulative Effort | Key Capability |
|-------|------|-------------------|----------------|
| 0 | 1 | 1 day | Clean foundation |
| 1 | 3 | 4 days | Single funnel, typed episodes |
| 2 | 2 | 6 days | Token budget enforcement |
| 3 | 3 | 9 days | Exact deduplication |
| 4 | 2 | 11 days | Full observability |
| 5 | 5 | 16 days | Utility-based retrieval |
| 6 | 10 | 26 days | Full SOTA (atoms, semantic dedup, contradictions) |

**Each phase is independently valuable.** You can stop at any phase and have a better system than before.

---

## Decision Points

### After Phase 1
- Is single funnel working well?
- Are configs covering all use cases?
- Continue to Phase 2?

### After Phase 3
- Is data quality acceptable?
- Are duplicates under control?
- Is semantic dedup needed (Phase 6) or is hash dedup sufficient?

### After Phase 5
- Is utility scoring improving retrieval?
- Are promotions happening correctly?
- Is the intelligence layer (Phase 6) worth the LLM cost?

---

## Files Created/Modified by Phase

### Phase 0
- MODIFY: `backend/app/services/memory/service.py`
- MODIFY: `backend/app/services/memory/golden_standards.py`

### Phase 1
- NEW: `backend/app/services/memory/types.py`
- NEW: `backend/app/services/memory/ingestion_config.py`
- NEW: `backend/app/services/memory/episode_creator.py`
- MODIFY: 15 caller files

### Phase 2
- NEW: `backend/app/services/memory/constants.py`
- MODIFY: `backend/app/services/memory/context_injector.py`

### Phase 3
- NEW: `backend/app/services/memory/dedup.py`
- NEW: `backend/scripts/memory/add_content_hashes.py`
- MODIFY: `backend/app/services/memory/episode_creator.py`

### Phase 4
- NEW: `backend/app/services/memory/metrics.py`
- NEW: `backend/scripts/memory/health_check.py`
- MODIFY: `backend/app/services/memory/episode_creator.py`
- MODIFY: `backend/app/services/memory/context_injector.py`

### Phase 5
- NEW: `backend/app/services/memory/utility.py`
- NEW: `backend/app/services/memory/promotion.py`
- MODIFY: `backend/app/services/memory/context_injector.py`

### Phase 6
- NEW: `backend/app/services/memory/atoms.py`
- NEW: `backend/app/services/memory/semantic_dedup.py`
- NEW: `backend/app/services/memory/contradictions.py`
- MODIFY: `backend/app/services/memory/episode_creator.py`
- MODIFY: Episode model (add atoms field)
