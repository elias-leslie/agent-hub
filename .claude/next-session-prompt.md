# Next Session: Verify & Implement `st complete` Fixes

## Context

We just completed 8 constraint/limit tasks (Tasks #16-#24) for the Agent Hub — raising timeouts, turn limits, concurrency, removing the artificial $5 SDK budget cap, etc. All committed and pushed (commit `0ed49bd`).

**Remaining: Task #15 — Fix `st complete` project auto-detection from cwd**

## What to Do

Launch **multiple agents in parallel** to verify the approach is sound before implementing:

### Agent 1: Explore `st create -P` pattern
Explore `/home/kasadis/summitflow/backend/cli/commands/create.py` and `/home/kasadis/summitflow/backend/cli/config.py` (specifically `_detect_project_from_cwd()` at line 108-117, `_resolve_project()` at line 120-131, and `require_explicit_project()` in `/home/kasadis/summitflow/backend/cli/_output_core.py` lines 75-95). Document exactly how the `-P` flag, env var, and cwd auto-detection work together. What edge cases exist? How does it handle no match?

### Agent 2: Explore `st complete` full code path
Explore `/home/kasadis/summitflow/backend/cli/commands/complete.py` and `/home/kasadis/summitflow/backend/cli/commands/_complete_http.py`. Trace how `project_id` flows from CLI flag → `call_complete()` → `build_payload()` → API request. Also check: does `max_turns` have a max=50 constraint in the CLI typer option (line 58) that needs updating to match the API's new le=200?

### Agent 3: Verify session_events observability gap
Run `st complete -a chat -x -n 5 -p agent-hub "List 3 files in the current directory using bash, then read one of them"` and check session_events for that session. Does `st complete -x` with proper project actually store tool_use events? The earlier "zero events" observation may have been from tests without `-x` or without a proper project. We need to confirm whether the gap is real or was just a testing artifact.

### Agent 4: Verify constraint changes are live
After restarting the worker (`bash ~/agent-hub/scripts/restart.sh`), verify:
- `MAX_CONCURRENT_SDK_SESSIONS` is now 6: `python -c "from app.adapters.claude_utils import MAX_CONCURRENT_SDK_SESSIONS; print(MAX_CONCURRENT_SDK_SESSIONS)"`
- `max_budget_usd` is gone from SDK options: `st complete -a chat "say hi" --raw | python -m json.tool` and check no budget errors
- Persona limits updated: `db query "SELECT limits FROM personas LIMIT 1"` — if limits is null, the defaults from `_persona_crud.py` apply (max_job_turns=50, dispatch_timeout_seconds=600)
- Scheduler timeout: check Hatchet dashboard or grep worker logs for "persona-scheduler" registration

## Proposed Implementation for Task #15

After verifying, implement:

1. **`/home/kasadis/summitflow/backend/cli/commands/complete.py`:**
   - Line 51: Change `project: ... = "st-cli"` to `project: ... = None` (make it Optional[str])
   - Line 58: Change `max=50` to `max=200`
   - Before `call_complete()`, add project resolution:
     ```python
     if not project:
         from ..config import _resolve_project
         project, _source = _resolve_project(project)  # flag > env > cwd > "st-cli"
     ```
   - If `_resolve_project` returns None (no match), fall back to `"st-cli"`

2. **`/home/kasadis/summitflow/backend/cli/commands/_complete_http.py`:**
   - Line 183: Change `project_id: str = "st-cli"` signature to match

3. **No write-blocking needed** — unlike `st create`, `st complete` doesn't create tasks. It runs completions. Wrong project just means wrong working directory context, not data corruption.

## Issues Table (from previous session)

| Issue | Severity | Status |
|---|---|---|
| st complete without -p = zero tool execution | High | Mitigated (Task #21 set st-cli root_path). Full fix = Task #15 |
| MCP persona tools timeout under load | Medium | Mitigated (Task #18 raised concurrency 3→6) |
| st complete -x tool_use events not in session_events | Medium | **NEEDS VERIFICATION** — may be testing artifact |
| Cron has full observability vs CLI has 0 | Low | **NEEDS VERIFICATION** — may be same artifact |

## After Implementation

- Run `dt -q -d` on summitflow changes
- Test: `cd /home/kasadis/agent-hub && st complete -a chat -x -n 3 "list files"` — should auto-detect project=agent-hub
- Test: `cd /home/kasadis/monkey-fight && st complete -a chat "what project am I in?"` — should auto-detect project=monkey-fight
- Test: `cd /tmp && st complete -a chat "hello"` — should fall back to st-cli
- Commit via /commit_it
