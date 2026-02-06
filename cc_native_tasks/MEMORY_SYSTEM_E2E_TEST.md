# Memory System E2E Test Plan

Post-implementation verification for the "Fix Broken Metrics + Close Gaps" work.
Run these tests sequentially in a fresh CC session.

---

## Pre-flight

```bash
# Verify services are running
systemctl --user is-active agent-hub-backend agent-hub-frontend agent-hub-celery neo4j
# Expected: all "active"

# Verify migration applied
db -P agent-hub query "SELECT version_num FROM alembic_version"
# Expected: b5c6d7e8f9a0

# Verify claude_code enum exists
db -P agent-hub query "SELECT unnest(enum_range(NULL::session_type_enum))"
# Expected: includes "claude_code"
```

---

## Phase 1: Citation Pipeline

### 1.1 session_id + project_id populated in metrics

```bash
st complete --agent coder --raw 'List the mandates from memory that apply to code quality'
```

Then verify:
```bash
db -P agent-hub query "SELECT session_id, project_id, external_id, reference_count, array_length(memories_loaded, 1) as loaded_count FROM memory_injection_metrics ORDER BY created_at DESC LIMIT 1"
```

**Expected:**
- `session_id` is NOT NULL (UUID format)
- `project_id` is NOT NULL (e.g., "st-cli")
- `loaded_count` > 0

### 1.2 memories_cited populated when LLM cites

```bash
st complete --agent coder --raw 'What does mandate M:b493dadc say? Quote it and cite it using Applied: [M:uuid8] format.'
```

Wait 2 seconds for async metrics update, then:
```bash
db -P agent-hub query "SELECT memories_cited FROM memory_injection_metrics ORDER BY created_at DESC LIMIT 1"
```

**Expected:**
- `memories_cited` is NOT empty `[]` - should contain at least one UUID

### 1.3 reference_count reflects actual references

```bash
db -P agent-hub query "SELECT reference_count, mandates_count, guardrails_count FROM memory_injection_metrics ORDER BY created_at DESC LIMIT 3"
```

**Expected:**
- `reference_count` may be 0 if no references triggered, but the code path uses `len(context.reference)` not hardcoded 0
- `mandates_count` > 0, `guardrails_count` > 0

---

## Phase 2: Utility Score Formula

### 2.1 Rate an episode and verify score update

```bash
# Pick an episode UUID
EPISODE_UUID=$(st memory list --limit 1 --format json | jq -r '.[0].uuid')

# Rate it as helpful
source ~/.env.local
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  -d '{"rating": "helpful"}' \
  "http://localhost:8003/api/memory/episodes/$EPISODE_UUID/rating"
```

Wait 35 seconds for usage buffer flush:
```bash
sleep 35
st memory get $EPISODE_UUID
```

**Expected:**
- `helpful_count` incremented by 1
- `utility_score` = `helpful / (helpful + harmful)` when both > 0
- OR `utility_score` = `referenced / loaded` as fallback when no helpful/harmful

### 2.2 Verify formula: helpful/(helpful+harmful)

```bash
# Rate same episode as harmful once
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  -d '{"rating": "harmful"}' \
  "http://localhost:8003/api/memory/episodes/$EPISODE_UUID/rating"

sleep 35
st memory get $EPISODE_UUID
```

**Expected:**
- If helpful=1, harmful=1 -> utility_score = 0.5
- If helpful=2, harmful=1 -> utility_score = 0.667

---

## Phase 3: Feedback Loop

### 3.1 Rating UI in frontend

1. Open http://localhost:3003/memory
2. Expand any episode row
3. Look for "Helpful" and "Harmful" buttons below the stats grid

**Expected:**
- Two buttons visible: green "Helpful" (thumbs-up), red "Harmful" (thumbs-down)
- Clicking "Helpful" increments the Helpful counter immediately
- Clicking "Harmful" increments the Harmful counter immediately
- Buttons show loading spinner while API call is in-flight

### 3.2 Auto-rate on citation

```bash
# Make a completion that will cite memories
st complete --agent coder --raw 'What does the mandate about comments say? Apply it and cite with Applied: [M:b493dadc]'
```

Wait 35 seconds for flush:
```bash
sleep 35
st memory get b493dadc
```

**Expected:**
- `helpful_count` incremented (auto-rated because cited in non-error response)
- `referenced_count` incremented (citation tracking)

---

## Phase 4: Reference Injection

### 4.1 --task-type flag works in graphiti-client

```bash
bash ~/.claude/hooks/graphiti-client.sh "database schema patterns" --project agent-hub --task-type database --debug
```

**Expected:**
- Output includes `<memory-debug>` block
- URL sent to API includes `&task_type=database`
- If references have `trigger_task_types` including "database", they appear in output

### 4.2 Configure trigger_task_types on a reference

```bash
# Find a reference episode
REF_UUID=$(db -P agent-hub query "
  SELECT e.uuid FROM memory_injection_metrics m
  CROSS JOIN LATERAL unnest(m.memories_loaded) AS loaded_uuid
  JOIN LATERAL (SELECT uuid FROM (SELECT 'placeholder' AS uuid) x) e ON true
  LIMIT 0
" 2>/dev/null || echo "")

# Or use the frontend: go to /memory, filter by "reference" tier, pick one
# Then set trigger types via the UI (Trigger Task Types section)
```

**Expected:**
- Reference episodes with matching `trigger_task_types` get injected when `task_type` matches

---

## Phase 5: CC Sessions as DB Citizens

### 5.1 Custom session_id creation (idempotent)

```bash
source ~/.env.local

# Create
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  -d '{"session_id": "e2e-test-session", "project_id": "agent-hub", "provider": "anthropic", "model": "claude-opus-4-6", "session_type": "claude_code"}' \
  http://localhost:8003/api/sessions | python3 -m json.tool

# Idempotent re-create (should return same session, not error)
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  -d '{"session_id": "e2e-test-session", "project_id": "agent-hub", "provider": "anthropic", "model": "claude-opus-4-6", "session_type": "claude_code"}' \
  http://localhost:8003/api/sessions | python3 -m json.tool
```

**Expected:**
- First call: 201 with `id: "e2e-test-session"`, `session_type: "claude_code"`
- Second call: 201 with identical response (same `created_at`)

### 5.2 Verify CC session exists in DB

```bash
db -P agent-hub query "SELECT id, project_id, session_type, status FROM sessions WHERE session_type = 'claude_code' ORDER BY created_at DESC LIMIT 5"
```

**Expected:**
- At least one row with `session_type = 'claude_code'`

### 5.3 Observation dual-store (Neo4j + PostgreSQL)

After using CC for a while (reading/writing files), check:
```bash
db -P agent-hub query "
  SELECT se.session_id, se.event_type, se.tool_name, LEFT(se.content, 80) as content_preview
  FROM session_events se
  JOIN sessions s ON se.session_id = s.id
  WHERE s.session_type = 'claude_code'
  ORDER BY se.created_at DESC
  LIMIT 10
"
```

**Expected:**
- Rows populated with `tool_use` events from CC observations
- `tool_name` reflects actual tools used (Read, Write, Edit, etc.)
- `content` contains observation narrative

### 5.4 Johnny hooks: session registration

Check johnny.log after starting a new CC session:
```bash
grep "Registered session" ~/.claude/plugins/johnny/johnny.log | tail -3
```

**Expected:**
- Log entries like: `[timestamp] [DEBUG] Registered session: <uuid> (project=agent-hub)`

### 5.5 Johnny hooks: summary trigger on stop

After ending a CC session, check:
```bash
grep "Summary triggered" ~/.claude/plugins/johnny/johnny.log | tail -3
```

**Expected:**
- Log entries like: `[timestamp] [INFO] Summary triggered: session=<uuid>`

### 5.6 Auto-generated summary stored

```bash
st memory search "session summary" --limit 5
```

**Expected:**
- Summary episodes appear from completed CC sessions
- Content contains structured summary with decisions, tools used, files modified

### 5.7 Summarize endpoint with project_id

```bash
source ~/.env.local

# Create a session with some events first (or use an existing one with events)
SESSION_WITH_EVENTS=$(db -P agent-hub query "
  SELECT DISTINCT se.session_id
  FROM session_events se
  JOIN sessions s ON se.session_id = s.id
  LIMIT 1
" -t 2>/dev/null | tr -d ' ')

curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  -d '{"project_id": "agent-hub"}' \
  "http://localhost:8003/api/memory/sessions/$SESSION_WITH_EVENTS/summarize" | python3 -m json.tool
```

**Expected:**
- Returns `SessionSummary` with `summary`, `key_decisions`, `tools_used`, `files_modified`, `topics`
- `episode_uuid` populated (stored in knowledge graph)

---

## Cleanup

```bash
# Delete test session
source ~/.env.local
curl -s -X DELETE \
  -H "X-Client-Id: $SUMMITFLOW_CLIENT_ID" \
  -H "X-Client-Secret: $SUMMITFLOW_CLIENT_SECRET" \
  -H "X-Request-Source: test" \
  http://localhost:8003/api/sessions/e2e-test-session
```

---

## Pass Criteria

| Phase | Test | Status |
|-------|------|--------|
| 1.1 | session_id + project_id in metrics | |
| 1.2 | memories_cited populated on citation | |
| 1.3 | reference_count not hardcoded | |
| 2.1 | Utility score updates on rating | |
| 2.2 | Formula: helpful/(helpful+harmful) | |
| 3.1 | Rating UI renders + works | |
| 3.2 | Auto-rate cited as helpful | |
| 4.1 | --task-type flag in graphiti-client | |
| 5.1 | Custom session_id (idempotent) | |
| 5.2 | claude_code sessions in DB | |
| 5.3 | Dual-store observations | |
| 5.4 | Session registration in johnny.log | |
| 5.5 | Summary trigger in johnny.log | |
| 5.6 | Auto-generated summaries exist | |
| 5.7 | Summarize endpoint with project_id | |

All 15 tests must pass for full verification.
