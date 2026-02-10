# E2E Test: Memory Analytics Self-Improvement

## Context

Implementation of three feedback loops for memory analytics is complete (session `fd046f61`). This task validates the full end-to-end flow with a running Agent Hub instance.

## Prerequisites

- Agent Hub backend running on port 8003 (`st logs tail -s agent-hub`)
- Neo4j running (port 7687)
- PostgreSQL running with agent_hub database

## Test Plan

### Test 1: Citation Parser — [R:uuid8] Support

```bash
# Unit test (already passes, quick sanity check)
source backend/.venv/bin/activate
python -m pytest backend/tests/services/memory/test_citation_parser.py -v -k "reference" --tb=short
```

**Expected**: All reference citation tests pass.

### Test 2: API — Analyze Endpoint (CC path)

```bash
# Create a test session first
SESSION_ID="e2e-analytics-$(date +%s)"

# Load env credentials
source <(grep -E '^SUMMITFLOW_CLIENT' ~/.env.local | sed 's/^/export /')

# Create a session via the sessions API (so we have a valid session_id)
curl -s -X POST http://localhost:8003/api/sessions \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -d "{\"id\": \"$SESSION_ID\", \"project_id\": \"test-project\", \"provider\": \"claude\", \"model\": \"test\"}" | jq .

# Now test the analyze endpoint with known citation prefixes
# First, find some real episode UUID prefixes:
# (pick 2-3 from: st memory list --limit 3)
# Or use known mandates from the memory-context block above

curl -s -X POST "http://localhost:8003/api/memory/sessions/$SESSION_ID/analyze" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -d '{"citation_prefixes": ["c37d31f2", "94dbfc89", "3daeb5da"]}' | jq .
```

**Expected**: Response shows `citations_found: 3`, `citations_credited` >= 1 (depends on which prefixes resolve in Neo4j).

### Test 3: API — Analyze Endpoint (API path, no body)

```bash
# Call analyze without body on a session that has session_events
# Use a real past session ID from the database:
# db query "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1"

REAL_SESSION=$(db query "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1" 2>/dev/null | tail -1 | tr -d ' ')

curl -s -X POST "http://localhost:8003/api/memory/sessions/$REAL_SESSION/analyze" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" | jq .
```

**Expected**: Response shows `citations_found` (may be 0 if no assistant messages had citations).

### Test 4: API — Task Outcome Endpoint (session-scoped)

```bash
curl -s -X POST "http://localhost:8003/api/memory/sessions/$SESSION_ID/task-outcome" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -d '{"succeeded": true, "task_id": "e2e-test-task"}' | jq .
```

**Expected**: Response shows `task_succeeded: true`, `metrics_updated` >= 0.

### Test 5: API — Task Outcome Endpoint (task-scoped)

```bash
curl -s -X POST "http://localhost:8003/api/memory/task-outcome" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -d '{"task_id": "e2e-test-task", "succeeded": true}' | jq .
```

**Expected**: Response shows `sessions_processed` >= 0, `total_memories_credited` >= 0.

### Test 6: Utility Score Formula (Neo4j)

```bash
# Check that the utility_score formula includes the new success_count tier
# Pick an episode with success_count > 0 after Test 4
python3 -c "
import asyncio
from app.services.memory.graphiti_client import get_graphiti

async def check():
    g = get_graphiti()
    records, _, _ = await g.driver.execute_query('''
        MATCH (e:Episodic)
        WHERE e.success_count > 0
        RETURN e.uuid AS uuid, e.loaded_count, e.success_count,
               e.referenced_count, e.utility_score
        LIMIT 5
    ''')
    for r in records:
        print(dict(r))
    if not records:
        print('No episodes with success_count > 0 yet (expected if no memories were loaded)')

asyncio.run(check())
"
```

### Test 7: Stop.sh Hook (manual)

Run a quick CC session that cites a memory rule, then verify:

```bash
# After ending a CC session that contains "[M:c37d31f2]" or similar:
tail -5 ~/.claude/plugins/johnny/johnny.log
# Should show both "Summary triggered" and "Citation scan triggered"
```

### Test 8: Summarize → Analyze Chain

```bash
# Trigger summarize on the test session — should auto-fire analyze as background task
curl -s -X POST "http://localhost:8003/api/memory/sessions/$SESSION_ID/summarize" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -d '{"project_id": "test-project"}' | jq .

# Check Agent Hub logs for "Citation scan" or "analyze_session" log lines
st logs tail -s agent-hub -l INFO | head -20
```

### Test 9: Full Test Suite Regression

```bash
source backend/.venv/bin/activate
python -m pytest backend/tests/services/memory/ backend/tests/api/test_memory.py backend/tests/api/test_memory_analysis.py -v --tb=short
```

**Expected**: 301 passed, 0 failed.

## Cleanup

```bash
# No persistent test data to clean — test session will be garbage collected
```

## Success Criteria

- [ ] All unit tests pass (301/301)
- [ ] `/analyze` endpoint credits resolved citations
- [ ] `/task-outcome` endpoint updates task_succeeded on metrics
- [ ] Task-scoped `/task-outcome` finds sessions by external_id
- [ ] Utility score formula uses success_count tier
- [ ] Stop.sh logs show citation scan triggered
- [ ] Summarize chains to analyze automatically
