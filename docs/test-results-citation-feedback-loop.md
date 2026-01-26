# Citation Feedback Loop - Test Results

**Date:** 2026-01-26
**Task:** task-181399fe - Agent citation feedback loop
**Status:** Complete with follow-up items identified

## Summary

All core functionality is working. The citation feedback loop successfully:
- Extracts citations from agent responses
- Tracks them in Neo4j with helpful_count/harmful_count
- Wires SummitFlow autonomous execution to Agent Hub rating API

## Test Results

### 1. Memory Injection (PASS)

**Test:** run_agent with `use_memory: true`

| Field | Result |
|-------|--------|
| session_id | `60db2fc1-8945-4224-91c9-8ebcea5f023d` (real UUID) |
| memory_uuids | 36 memories injected |
| cited_uuids | 13 memories cited by agent |

- Session persists in database
- Memory injection works correctly with global scope
- Citations extracted from `[M:uuid]` and `[G:uuid]` format

### 2. Rating API (PASS)

**Endpoint:** `POST /api/memory/episodes/{uuid}/rating`

| Test | Result |
|------|--------|
| helpful rating | `helpful_count` incremented |
| harmful rating | `harmful_count` incremented |
| used rating | `referenced_count` incremented |
| Multiple ratings | Counts accumulate correctly |
| Buffer flush | ~1-2 second delay, then persisted to Neo4j |

### 3. Citation Prefix Resolution (PASS)

**Function:** `extract_uuid_prefixes()` and `resolve_full_uuids()`

| Test Case | Result |
|-----------|--------|
| `[M:279b1026]` | Extracted correctly |
| `[G:afe5d669]` | Extracted correctly |
| Empty content | Returns `[]` |
| Malformed citations | Ignored correctly |
| Duplicates | Deduplicated |
| Case insensitive | Normalized to lowercase |

Regex pattern: `\[([MG]):([a-f0-9]{8})\]`

### 4. Tier Optimizer Thresholds (PASS)

**Configured thresholds:**
- `HARMFUL_COUNT_THRESHOLD = 3` (demotion)
- `HELPFUL_COUNT_THRESHOLD = 5` (promotion)

**Current database state:**
- Max harmful_count: 1
- Max helpful_count: 1
- No episodes currently meet thresholds

Functions `find_demotion_candidates()` and `find_promotion_candidates()` work correctly.

### 5. SDK Integration (PASS with gaps)

**Working:**
- `rate_episode(uuid, rating)` method
- `AgentRunResponse` includes `session_id`, `memory_uuids`, `cited_uuids`

**SDK needs updates** (see follow-up items below)

### 6. SummitFlow Citation Flow (PASS)

**Function:** `log_citations()` in subtasks.py

- Parses suffix notation (`M:abc+` -> helpful, `M:abc-` -> harmful)
- Handles plain UUIDs (defaults to "used")
- Calls `client.rate_episode()` for each citation
- Stores in `subtask_citations` table

---

## Issues Found

### 1. Multi-turn Citation Accumulation (GAP)

**Decision d4:** "Citations aggregated across turns"

**Issue:** Citations only extracted on turn 1. Subsequent turns use `adapter.complete()` which doesn't extract citations.

**Location:** `/home/kasadis/agent-hub/backend/app/services/agent_runner.py` lines 298-301

**Impact:** Low - most agent runs complete in 1 turn. Tool use scenarios may miss citations from turns 2+.

**Fix:** Add citation extraction after subsequent turns (when `adapter.complete()` is used).

### 2. No UUID Validation in Rating API

**Issue:** The rating API accepts any string as UUID. Non-existent UUIDs silently succeed (buffered but never written to Neo4j).

**Location:** `/home/kasadis/agent-hub/backend/app/api/memory.py:1351`

**Impact:** Low - callers pass valid UUIDs from `cited_uuids` response.

**Potential fix:** Add UUID format validation or check episode exists before accepting rating.

### 3. SDK Missing Parameters

**SDK `run_agent` method missing:**
- `project_id` (API defaults to "agent-hub")
- `use_memory` (API defaults to True)
- `memory_group_id` (API defaults to None/global)
- `thinking_level` (API accepts minimal/low/medium/high/ultrathink)

**Location:** `/home/kasadis/agent-hub/packages/agent-hub-client/agent_hub/client.py`

**Impact:** Medium - SummitFlow passes these via API directly, but other SDK users can't access these features.

---

## Follow-up Items

### High Priority - DONE

1. **Update SDK to include new parameters:** ✅ Completed 2026-01-26
   - Added `project_id`, `use_memory`, `memory_group_id`, `thinking_level` to both sync and async `run_agent` methods
   - File: `packages/agent-hub-client/agent_hub/client.py`

### Medium Priority - DONE

2. **Add citation extraction for multi-turn scenarios:** ✅ Completed 2026-01-26
   - Added `extract_uuid_prefixes` + `resolve_full_uuids` after `adapter.complete()` in subsequent turns
   - Citations from turns 2+ now accumulate in `all_cited_uuids`
   - File: `backend/app/services/agent_runner.py`

### Low Priority - DONE

3. **Add UUID validation to rating API:** ✅ Completed 2026-01-26
   - Added `uuid_module.UUID(uuid)` validation before processing rating
   - Returns HTTP 422 for invalid UUID format
   - File: `backend/app/api/memory.py`

### Remaining (deferred)

4. **Consider exposing rating counts in API:**
   - Add `helpful_count`/`harmful_count` to episode details endpoint
   - Useful for debugging and observability

---

## Test Commands Reference

```bash
# Test run_agent with memory
curl -X POST http://localhost:8003/api/orchestration/run-agent \
  -H "Content-Type: application/json" \
  -H "X-Agent-Hub-Internal: agent-hub-internal-v1" \
  -d '{"task": "...", "agent_slug": "coder", "max_turns": 1, "project_id": "agent-hub"}'

# Test rating API
curl -X POST http://localhost:8003/api/memory/episodes/{uuid}/rating \
  -H "Content-Type: application/json" \
  -d '{"rating": "helpful"}'

# Check Neo4j counts
cd ~/agent-hub/backend && .venv/bin/python -c "
import asyncio
from app.services.memory.graphiti_client import get_graphiti
g = get_graphiti()
r, _, _ = asyncio.run(g.driver.execute_query(
    'MATCH (e:Episodic {uuid: \"{uuid}\"}) RETURN e.helpful_count, e.harmful_count'
))
print(r)
"

# Check tier optimizer candidates
cd ~/agent-hub/backend && .venv/bin/python -c "
import asyncio
from app.services.memory.tier_optimizer import find_demotion_candidates, find_promotion_candidates
print('Demotions:', len(asyncio.run(find_demotion_candidates())))
print('Promotions:', len(asyncio.run(find_promotion_candidates())))
"
```

---

## Architecture Notes

### Flow: Agent Response -> Citation Tracking

```
1. run_agent called
   └─> complete_internal() on turn 1
       ├─> Memory injection (use_memory=true)
       ├─> LLM completion
       ├─> extract_uuid_prefixes(response.content)
       ├─> resolve_full_uuids(prefixes, group_id)
       └─> track_referenced_batch(cited_uuids)

2. AgentRunResponse returned
   ├─> session_id (real DB session)
   ├─> memory_uuids (what was injected)
   └─> cited_uuids (what agent referenced)

3. SummitFlow receives response
   └─> log_citations(task_id, subtask_id, cited_uuids, client)
       ├─> Store in subtask_citations table
       └─> client.rate_episode(uuid, "used") for each
```

### Flow: Rating -> Neo4j

```
1. POST /api/memory/episodes/{uuid}/rating
   └─> track_helpful() or track_harmful() or track_referenced()
       └─> UsageBuffer.increment_*()

2. Buffer accumulates updates (30s interval)

3. Buffer flush
   └─> _flush_to_neo4j()
       └─> MATCH (e:Episodic {uuid: ...})
           SET e.helpful_count = COALESCE(e.helpful_count, 0) + $delta
```

### ACE-Aligned Tier Optimization

```
find_demotion_candidates():
  WHERE e.harmful_count >= 3  # HARMFUL_COUNT_THRESHOLD

find_promotion_candidates():
  WHERE e.helpful_count >= 5  # HELPFUL_COUNT_THRESHOLD

Secondary signal (no ratings):
  WHERE e.loaded_count >= 50 AND age >= 7 days
```
