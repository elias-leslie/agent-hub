# WS11 Validation Pass v2 — Full E2E Verification

## Background

Previous session completed:
1. **Full plan review** — All 11 workstreams verified as implemented
2. **Outage investigation** — Jenny couldn't fix SF backend outage because she had write-only permission on summitflow. Fixed: upgraded to yolo+auto_exec on both summitflow and agent-hub.
3. **Heartbeat concurrency bug** — Hatchet's CANCEL_IN_PROGRESS was killing running heartbeats when the cron trigger fired. Fixed: changed to CANCEL_NEWEST.
4. **CLI fix** — `st session-events` was broken (Typer group pattern made options unusable after positional arg). Fixed: converted to plain command.
5. **Soft turn limit** — Replaced hard max_turns=25 with soft limit at 100 turns + checkpoint prompt injection every 10 turns after. Hard cap at 200. Jenny self-regulates instead of being cut off.
6. **Memory cleanup** — Deleted 7 stale heartbeat error memories (exit code -15 from CANCEL_IN_PROGRESS bug). Updated model selection memory. Saved new mandates for heartbeat concurrency and CLI-first obligation.

### Commits from This Session

| Repo | Hash | Description |
|------|------|-------------|
| agent-hub | `dd95180` | fix: Change heartbeat concurrency to CANCEL_NEWEST |
| summitflow | `21638686` | fix(cli): Convert session-events from Typer group to plain command |
| agent-hub | `1c3da71` | feat: Soft turn limit with checkpoint messages (100 soft, 200 hard) |

### Previous Session Commits (WS1-WS10)

| Repo | Hash | Description |
|------|------|-------------|
| summitflow | `07dc185d` | WS2: Remove dead qa_status columns |
| summitflow | `bc19f44c` | WS1: Fix false completions — require work product |
| summitflow | `eaba4b15` | WS5: Human language cleanup |
| agent-hub | `104dd9e` | WS5+8: Human language + remove COMPONENT_FRICTION |
| agent-hub | `79b9f05` | WS3: Model routing changes |
| agent-hub | `f28c0be` | WS4: Failed work + backlog in heartbeat data |
| summitflow | `990311dc` | WS9: Persona CLI commands |
| summitflow | `6061dd9b` | WS10: Lifecycle events to Agent Hub |
| summitflow | `939f2a65` | Fix: Correct ah_events import path (caused outage) |

## Tasks for This Session

### 1. Re-verify All 11 Workstreams (Regression Check)

Run all verification commands from the original plan to confirm nothing regressed:

**Phase A verification:**
```bash
# WS1: Work product check exists and is called
grep -n "_has_work_product" ~/summitflow/backend/app/tasks/autonomous/exec_modules/steps.py

# WS2: Dead qa_status columns removed (qa_issues TABLE is legitimate)
grep -rn "qa_status\|qa_signoff_at\|qa_signoff_by" ~/summitflow/backend/app/

# WS5: Human language cleaned
grep -rn "escalate_to_human\|needs-human-review\|COMPONENT_FRICTION\|_notify_human" ~/summitflow/backend/app/ ~/agent-hub/backend/app/

# WS8: COMPONENT_FRICTION removed
grep -rn "COMPONENT_FRICTION" ~/agent-hub/backend/app/
```

**Phase B verification:**
```bash
# WS3: Model routing changes
grep -n "fallback_models" ~/agent-hub/backend/app/models/agent.py
# Confirm tier_preference is gone
! grep -n "tier_preference" ~/agent-hub/backend/app/api/complete/request_schemas.py
```

**Phase C verification:**
```bash
# WS4: Failed work + backlog in heartbeat data
grep -n "_fetch_failed_work_section\|_fetch_backlog_summary_section" ~/agent-hub/backend/app/workflows/_heartbeat_data.py

# WS6+7: Heartbeat instructions
db -P agent-hub query "SELECT length(heartbeat_instructions) FROM persona WHERE id = 1"
# Verify contains: "Progress Drive", MUST/NEVER directives, escalation clarity, backlog hygiene
```

**Phase D verification:**
```bash
# WS9: CLI commands work
st persona heartbeat --help && st persona activity --help && st persona status

# WS10: ah_events imports correct
grep -rn "from.*ah_events import" ~/summitflow/backend/app/
# Should show 3 correct imports
```

### 2. Verify New Fixes from This Session

```bash
# Heartbeat concurrency: CANCEL_NEWEST
grep -n "CANCEL_NEWEST" ~/agent-hub/backend/app/workflows/persona_heartbeat.py

# Session-events CLI works with all options
st session-events --help  # Should NOT show "COMMAND [ARGS]..." in usage
# Test with a real session:
db -P agent-hub query "SELECT id FROM sessions WHERE agent_slug = 'persona' ORDER BY created_at DESC LIMIT 1"
# Then: st session-events <id> --page 1
# And:  st session-events <id> -t tool_use

# Soft turn limit
grep -n "soft_limit" ~/agent-hub/backend/app/api/complete/multi_turn_loop.py
grep -n "soft_limit" ~/agent-hub/backend/app/api/complete/multi_turn_helpers.py
grep -n "max_turns=100" ~/agent-hub/backend/app/workflows/persona_heartbeat.py

# Jenny's permissions
db -P agent-hub query "SELECT project_id, permission_tier, auto_exec_enabled FROM project_permissions WHERE project_id IN ('summitflow', 'agent-hub')"
# Both should be yolo + auto_exec_enabled=true
```

### 3. Trigger Validation Heartbeat and Evaluate

```bash
st persona heartbeat --watch
```

After completion, evaluate against ALL 10 criteria:

| # | Criteria | How to Check |
|---|----------|-------------|
| 1 | Reviews active work BEFORE creating new tasks | First tool call after orient should be `manage_tasks(action="list_active")` |
| 2 | Acts on `<failed_work>` items | Look for `get_context` calls on failed/abandoned tasks |
| 3 | Schedules follow-ups for dispatched code work | Look for `schedule_job` calls after any `manage_tasks(action="dispatch")` |
| 4 | Drives forward progress (completed work, not just dispatched) | Did the heartbeat produce real outcomes? |
| 5 | Triages ≥2 feedback items when open items exist | Look for ≥2 `manage_feedback` calls with action=resolve/vote |
| 6 | Journals with type rotation | Check for `write_journal` call |
| 7 | Prunes stale backlog items (>7 days pending) | Look for cancel/delete actions on old tasks |
| 8 | Uses directive language accurately (MUST/NEVER honored) | Did she violate any Hard Rules? |
| 9 | Escalates only for genuine decision points | Did she push notification appropriately? |
| 10 | Token-efficient output | Was the output focused, no rambling? |

To check session events:
```bash
db -P agent-hub query "SELECT id FROM sessions WHERE agent_slug = 'persona' ORDER BY created_at DESC LIMIT 1"
st session-events <session-id>
st session-events <session-id> -t tool_use
st session-events <session-id> -t thinking
```

### 4. Verify Soft Limit Checkpoint Behavior

The checkpoint message is injected at the soft limit (turn 100) and every 10 turns after. It must NOT cause Jenny to prematurely stop or "wrap up" — it should be a quick self-check that lets her keep working.

**Step 1: Verify the checkpoint message text is non-disruptive.**

Read the current checkpoint message:
```bash
grep -A 10 "_CHECKPOINT_MSG" ~/agent-hub/backend/app/api/complete/multi_turn_loop.py
```

Verify it:
- Explicitly says "this is NOT a signal to stop"
- Says "you have plenty of capacity remaining"
- Only asks two quick questions (progressing? looping?)
- Ends with "Resume your work now"
- Does NOT say "wrap up", "finish", "close out", or anything that implies stopping

**Step 2: Test checkpoint injection with a low soft limit.**

Temporarily test with soft_limit=5 to verify it injects correctly and doesn't confuse the agent:

```bash
# Use st complete with a low max_turns to trigger the checkpoint
st complete -a persona -n 5 "List 3 random fun facts. After each fact, say 'continuing...' and list the next."
```

Check the session events for the checkpoint injection:
```bash
db -P agent-hub query "SELECT id FROM sessions WHERE agent_slug = 'persona' ORDER BY created_at DESC LIMIT 1"
st session-events <session-id> -v
```

Verify:
- The `<system-checkpoint>` message appears at turn 5
- The agent does NOT treat it as a stop signal (continues working)
- The agent acknowledges it briefly (or ignores it) and continues
- If the agent stops prematurely after the checkpoint, the message needs rewording

**Step 3: If the checkpoint causes premature stopping, reword it.**

The message must feel like a gentle background nudge, not an interruption. Consider:
- Making it shorter
- Using `<system-reminder>` tag instead (models are trained to treat these as low-priority)
- Removing any question that implies the agent should evaluate whether to stop

**Step 4: Verify the injection mechanics.**

```bash
# Check _needs_checkpoint logic
grep -A 5 "_needs_checkpoint" ~/agent-hub/backend/app/api/complete/multi_turn_loop.py

# Verify soft_limit is wired correctly
grep -n "soft_limit" ~/agent-hub/backend/app/api/complete/multi_turn_executor.py
# Should show: soft_limit=max_turns, max_turns=max_turns*2
```

### 5. Fix Any Issues Found

If heartbeat reveals gaps:
- **Instruction gap** → edit the DB-backed instructions via `st persona instructions -e` (or import a draft once with `st persona update --heartbeat-instructions <file>`)
- **Data gap** → edit `~/agent-hub/backend/app/workflows/_heartbeat_data.py`
- **Permission gap** → update project_permissions via db CLI
- **Tool gap** → check tool availability in persona agent config

### 6. Validate Heartbeat Pass Count

The WS11 success criteria require **3 consecutive heartbeats passing ALL 10 criteria**. Previous passes:
- Pass #1: During outage — incomplete (services were down)
- Pass #2: This session — 7/10 passed (missed journal, backlog pruning, follow-up scheduling due to max_turns=25)

This session should complete passes #2 (with fixes) and #3.

## Key Files Reference

| File | Purpose |
|------|---------|
| `~/agent-hub/backend/app/api/complete/multi_turn_loop.py` | Turn loop with soft limit checkpoint injection |
| `~/agent-hub/backend/app/api/complete/multi_turn_helpers.py` | TurnLoopConfig with soft_limit fields |
| `~/agent-hub/backend/app/api/complete/multi_turn_executor.py` | Config builder (soft_limit = max_turns, hard cap = 2x) |
| `~/agent-hub/backend/app/workflows/persona_heartbeat.py` | Heartbeat workflow (max_turns=100, CANCEL_NEWEST) |
| `~/agent-hub/backend/app/workflows/_heartbeat_data.py` | Heartbeat data (active work, failed work, backlog) |
| `~/agent-hub/backend/app/workflows/_heartbeat_postprocess.py` | Post-heartbeat processing (dispatch retry, default max_turns=100) |
| `~/summitflow/backend/cli/commands/session_events.py` | Fixed session-events CLI (plain command, not Typer group) |
