# WS11 Validation Pass — Investigate Outage + Fix Gaps + Retest

## Background

We completed a large 11-workstream plan to harden Jenny's autonomous task execution. During the first validation heartbeat (WS11), Jenny detected that the SummitFlow backend (port 8001) was down and correctly pushed a notification — but she didn't fix it herself.

The outage was caused by **our own code change** in WS10. We added `ah_events.py` to `exec_modules/` but used the wrong import path in `review_modules/routing.py`:

```python
# WRONG (resolved to app.tasks.autonomous.ah_events — doesn't exist)
from ..ah_events import emit_review_verdict, emit_task_transition

# FIXED (correct path)
from ..exec_modules.ah_events import emit_review_verdict, emit_task_transition
```

This caused a `ModuleNotFoundError` on uvicorn worker respawn, crashing the SummitFlow backend. The fix was committed as `939f2a65` and services restarted. SummitFlow is confirmed back up.

## Tasks for This Session

### 0. Full Plan Review — Verify Every Workstream Was Completed

Read the full implementation plan at **`/home/kasadis/.claude/plans/vivid-crunching-clover.md`** end-to-end. For each of the 11 workstreams, verify:

1. **Every file listed in the plan was actually modified** — read each file and confirm the described changes exist
2. **Every behavioral change described actually works** — don't just check the code exists, test it
3. **No partial implementations** — if the plan says "add X, Y, and Z", verify all three are present
4. **No regressions** — changes didn't break existing functionality
5. **Verification steps from the plan pass** — the plan includes specific verification commands per phase, run them all

Pay special attention to:
- **WS1 (false completions)**: Does `_has_work_product()` actually get called in the execution flow? Trace the call path.
- **WS3 (model routing)**: Verify specialist agents use their primary model by default and only switch models through explicit override, escalation, or true fallback.
- **WS4 (heartbeat data)**: Trigger a heartbeat and verify `<failed_work>` and `<backlog_summary>` sections actually appear in the prompt (not just that the functions exist).
- **WS5 (human language)**: Run the full grep verification: `grep -rn "escalate_to_human\|needs-human-review\|COMPONENT_FRICTION\|_notify_human" ~/summitflow/backend/app/ ~/agent-hub/backend/app/` — must be zero results.
- **WS6+7 (instructions)**: Read the actual DB instructions and compare against the plan's requirements. Are all the specific additions there? (driving progress mandate, backlog hygiene, dispatch tracking rule, escalation clarity, "Progress Drive" not "Creative Scan")
- **WS10 (lifecycle events)**: The import bug that caused the outage was in this workstream. Are there any other integration issues? Try importing every module that uses `ah_events` in Python to verify.

Document any gaps found, fix them, and note what was missing.

### 1. Investigate: Why Didn't Jenny Fix the Outage?

Jenny detected the outage and sent a push notification, but didn't attempt to fix it. Investigate:

- Check Jenny's current project permissions: `db -P agent-hub query "SELECT project_id, permission_tier, auto_exec_enabled FROM project_permissions ORDER BY project_id"`
- Jenny's `summitflow` permission tier is likely `read` (not `yolo` or `auto-exec`). Confirm this.
- Check her heartbeat instructions — does anything tell her to investigate service failures? The new instructions say:
  > `<failed_work>` items → investigate via `get_context`. Create fix task or delete if stale.
  But this refers to *task* failures, not *service* failures.
- Check if she has bash access on summitflow: look at her tool_permissions in the agent config.

**Key questions to answer:**
1. Could Jenny have diagnosed the import error from the logs? (Does she have access to `journalctl` or `st logs`?)
2. Could she have restarted the service? (Does she have permission to run `restart.sh`?)
3. Could she have created a task to fix the import error? (She'd need `auto_exec_enabled` on summitflow)
4. Should she have tried harder before just sending a push notification?

**Decision needed:** Should Jenny's heartbeat instructions include a "service recovery" phase? E.g.:
- If a managed service is down, check logs (`st logs tail -s <service> -n 20`)
- If the error is an import/syntax error from a recent commit, create a bug-fix task
- If she can't fix it, THEN push notification with the error details

### 2. Verify All Services Are Healthy

```bash
curl -s http://localhost:8001/api/projects | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))" | head -5  # SummitFlow
curl -s http://localhost:8003/api/health  # Agent Hub
curl -s http://localhost:3001 > /dev/null && echo "SF Frontend OK" || echo "SF Frontend DOWN"
curl -s http://localhost:3003 > /dev/null && echo "AH Frontend OK" || echo "AH Frontend DOWN"
st persona status
```

### 3. Check for Outstanding Issues from the 11-Workstream Plan

Review what was done and verify nothing is broken:

**Phase A (SummitFlow pipeline fixes):**
- WS1: `_has_work_product()` in `~/summitflow/backend/app/tasks/autonomous/exec_modules/steps.py` — verify the function exists and works
- WS2: `grep -rn "qa_status\|qa_signoff" ~/summitflow/backend/app/` — should return zero results
- WS5: `grep -rn "escalate_to_human\|needs-human-review\|COMPONENT_FRICTION" ~/summitflow/backend/app/ ~/agent-hub/backend/app/` — should return zero results
- Run `dt --check` on summitflow to verify no regressions

**Phase B (Model tier):**
- WS3: `! grep -n "premium_model_id\\|tier_preference" ~/agent-hub/backend/app/api/complete/request_schemas.py ~/agent-hub/backend/app/models/agent.py`
- Verify model routing still supports fallback chains: `grep -n "fallback_models" ~/agent-hub/backend/app/models/agent.py`

**Phase C (Heartbeat context + instructions):**
- WS4: Verify `<failed_work>` and `<backlog_summary>` sections appear in heartbeat prompt. Check `~/agent-hub/backend/app/workflows/_heartbeat_data.py` for `_fetch_failed_work_section` and `_fetch_backlog_summary_section`
- WS6+7: `db -P agent-hub query "SELECT length(heartbeat_instructions) FROM persona WHERE id = 1"` — should be ~4000 chars (~800 tokens). Verify instructions contain "Progress Drive" (not "Creative Scan") and MUST/NEVER directive language

**Phase D (CLI + timeline events):**
- WS9: `st persona heartbeat --help && st persona activity --help && st persona status` — all three commands should work
- WS10: Verify `ah_events.py` imports are correct (the bug we just fixed):
  ```bash
  grep -rn "from.*ah_events import" ~/summitflow/backend/app/
  ```
  Should show 3 correct imports (2 from `.ah_events`, 1 from `..exec_modules.ah_events`)

### 4. Trigger Validation Heartbeat #2

After confirming everything is healthy:

```bash
st persona heartbeat --watch
```

Then evaluate against these criteria (from the plan):

| # | Criteria | How to Check |
|---|----------|-------------|
| 1 | Reviews active work BEFORE creating new tasks | First tool call after orient should be `manage_tasks(action="list_active")` |
| 2 | Acts on `<failed_work>` items | Look for `get_context` calls on failed/abandoned tasks |
| 3 | Schedules follow-ups for dispatched code work | Look for `schedule_job` calls after any `manage_tasks(action="dispatch")` |
| 4 | Drives forward progress (completed work, not just dispatched) | Did the heartbeat produce real outcomes, not just task creation? |
| 5 | Triages ≥2 feedback items when open items exist | Look for ≥2 `manage_feedback` calls with action=resolve/vote |
| 6 | Journals with type rotation | Check journal entry type vs recent types |
| 7 | Prunes stale backlog items (>7 days pending) | Look for cancel/delete actions on old tasks |
| 8 | Uses directive language accurately (MUST/NEVER honored) | Did she violate any Hard Rules? |
| 9 | Escalates only for genuine decision points | Did she push notification appropriately? |
| 10 | Token-efficient output | Was the output focused, no rambling? |

To check the session events:
```bash
# Get the latest persona session ID
db -P agent-hub query "SELECT id, summary_oneliner FROM sessions WHERE agent_slug = 'persona' ORDER BY created_at DESC LIMIT 1"

# Then view events
st session-events <session-id>
```

### 5. Fix Any Issues Found

If the heartbeat reveals gaps:
- **Instruction gap** → edit the DB-backed instructions via `st persona instructions -e` (or import a draft once with `st persona update --heartbeat-instructions <file>`)
- **Data gap** → edit `~/agent-hub/backend/app/workflows/_heartbeat_data.py`
- **Permission gap** → update project_permissions: `db -P agent-hub exec "UPDATE project_permissions SET permission_tier='yolo', auto_exec_enabled=1 WHERE project_id='summitflow'"`
- **Tool gap** → check tool availability in persona agent config

After any fix, restart affected service and re-trigger heartbeat.

## Key Files Reference

| File | Purpose |
|------|---------|
| `~/agent-hub/backend/app/workflows/_heartbeat_data.py` | Data-fetching for heartbeat prompt (active work, failed work, backlog, git state, feedback) |
| `~/agent-hub/backend/app/workflows/_heartbeat_templates.py` | Heartbeat prompt template (per-session) |
| `~/agent-hub/backend/app/workflows/persona_heartbeat.py` | Heartbeat orchestration |
| `~/summitflow/backend/app/tasks/autonomous/exec_modules/ah_events.py` | Lifecycle event emitter (review verdicts, quality gate, task transitions → AH session_events) |
| `~/summitflow/backend/app/tasks/autonomous/review_modules/routing.py` | Review verdict routing (APPROVED/NEEDS_FIX/ESCALATE) |
| `~/summitflow/backend/app/tasks/autonomous/exec_modules/quality_gate.py` | Quality gate with auto-fix |
| `~/summitflow/backend/app/tasks/autonomous/exec_modules/completion_handler.py` | Task completion/failure handling |
| `~/summitflow/backend/app/tasks/autonomous/exec_modules/steps.py` | Work product check (`_has_work_product()`) |
| `~/summitflow/backend/cli/commands/persona.py` | ST CLI persona commands (heartbeat, activity, status) |
| `~/summitflow/backend/cli/commands/persona_api.py` | API client for persona CLI |
| `~/agent-hub/backend/scripts/seed_agents_data/core_agents.py` | Agent seed data and prompts |
| `~/agent-hub/backend/scripts/seed_agents_data/_execution_agents.py` | Execution agent seed data |

## Commits from This Work

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

## Previous Plan Reference

The full plan is at: `~/.claude/plans/vivid-crunching-clover.md`

The WS11 success criteria require 3 consecutive heartbeats passing ALL criteria. We've done 1 pass so far (with the service outage complicating evaluation). This session should complete pass #2 and ideally #3.
