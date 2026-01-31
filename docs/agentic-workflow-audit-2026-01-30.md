# SummitFlow Agentic Workflow Audit

**Date:** 2026-01-30
**Status:** Audit Complete
**Recommendation:** Consolidate to Autonomous Pipeline

---

## Executive Summary

SummitFlow has **4 different agentic code execution workflows** that evolved separately. Only **1 workflow** (Autonomous Execution) uses the current architecture: `agent_slug` routing, memory injection, and `verify_command` verification. The other 3 are legacy and should be consolidated or removed.

### Recommended Actions

**Phase 1: Migrate Features (Before Removal)**
1. **Migrate pristine check** from Orchestrator → Autonomous
   - `dt --check` runs before execution to ensure codebase is clean
   - Location: `orchestrator_runner.py:check_pristine_codebase()`
   - Target: `autonomous/execution.py:start_execution()`

2. **Migrate chat message context** (if needed for human-in-loop)
   - User directions passed to agent during execution
   - Location: `orchestrator/execution.py:build_prompt()`
   - Target: `autonomous/execution.py:_build_subtask_prompt()`

**Phase 2: Remove Legacy Code**
1. **REMOVE**: `--sync` flag from `st autocode` - evidence contract is legacy
2. **REMOVE**: Orchestrator service (`/execute` API) - uses raw provider/model, no agent_slug
3. **REMOVE**: Implementation Executor - orphaned, never called in production
4. **REMOVE**: Agent Runner - marks tasks complete without verification

**What STAYS:**
- `st autocode <task-id>` (default, async) - triggers Autonomous pipeline
- Autonomous Execution (`tasks/autonomous/execution.py`) - sole production path
- All autonomous/* modules (triage, planning, execution, review, escalation)

---

## Workflow Comparison Matrix

| Dimension | Autonomous | Orchestrator | Sync Autocode | Agent Runner |
|-----------|------------|--------------|---------------|--------------|
| **Entry Point** | `st autocode` (default) | POST `/execute` | `st autocode --sync` | POST `/start` |
| **File Location** | `tasks/autonomous/execution.py` | `services/orchestrator/` | `services/agent_hub.py` | `tasks/agent_runner.py` |
| **Agent Call** | `run_agent()` | `run_agent()` | `generate()` | `generate()` |
| **Uses agent_slug** | ✅ Yes (`"coder"`) | ❌ No (raw provider/model) | ⚠️ Partial | ✅ Yes |
| **Memory Injection** | ✅ `use_memory=True` | ❌ No | ❌ No | ❌ No |
| **Verification** | ✅ `verify_step()` | ❌ Text parsing | ❌ Evidence contract | ❌ None |
| **Multi-turn** | ✅ max_turns=30 | ✅ max_turns=20 | ❌ Single turn | ❌ Single turn |
| **Fresh Context** | ✅ Per subtask | ❌ Accumulated | ❌ N/A | ❌ N/A |
| **Worktree Isolation** | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| **Escalation** | ✅ 3-2-1 pattern | ❌ Retry only | ❌ Retry only | ❌ Retry only |
| **QA Review** | ✅ AI review flow | ⚠️ Opus review | ❌ None | ❌ None |
| **Status After** | `ai_reviewing` | `ai_reviewing` | Inline return | `completed` |
| **Celery Task** | `autonomous.start_execution` | `execute_orchestrator_task` | None (sync) | `run_agent_task` |
| **Actually Used** | ✅ Production | ⚠️ Rarely | ⚠️ Debug only | ⚠️ Legacy |

---

## Detailed Analysis

### 1. Autonomous Execution ✅ KEEP
**Location:** `/home/kasadis/summitflow/backend/app/tasks/autonomous/execution.py`

**Entry Points:**
- `st autocode <task_id>` → sets status to "queue" → triggers Celery task
- Status change to "queue" via API → `_dispatch_autonomous_task()`

**Correct Features:**
```python
# Uses agent_slug (not raw model)
response = client.run_agent(
    task=prompt,
    agent_slug="coder",
    working_dir=worktree_path,
    max_turns=30,
    project_id=project_id,
    use_memory=True,  # Memory injection enabled
)

# Uses verify_command (not text parsing)
result = verify_step(step, worktree_path, project_id=project_id)
```

**Architecture:**
- Fresh context per subtask with handoff summaries
- Task spirit + objective injected
- Worktree isolation per task
- 3-2-1 escalation: worker → supervisor → human
- AI review → auto-merge flow

---

### 2. Orchestrator Service ❌ DEPRECATE
**Location:** `/home/kasadis/summitflow/backend/app/services/orchestrator/`

**Entry Points:**
- POST `/projects/{project_id}/tasks/{task_id}/execute`

**Legacy Issues:**
```python
# Uses raw provider/model - NO agent_slug
result = await client.run_agent(
    task=prompt,
    provider=provider,  # "claude" or "gemini"
    model=model,        # raw model name
    system_prompt="...",
    max_turns=20,
    enable_code_execution=(provider == "claude"),
    working_dir=str(effective_repo_path),
)

# Uses heuristic text parsing - NOT verify_command
def analyze_execution_result(content: str, subtask: dict) -> tuple[bool, str | None]:
    if "done:" in content_lower or "completed successfully" in content_lower:
        return True, None
    # ...fails to detect actual verification
```

**What It Has:**
- Pristine codebase check (`dt --check`) before execution
- Worktree isolation
- Chat message context (user directions)
- Draft PR creation + Opus review

**Migration Path:**
- Move pristine check to Autonomous pipeline
- Move chat message support if needed
- Remove orchestrator service entirely

---

### 3. Sync Autocode (Evidence Contract) ❌ DEPRECATE
**Location:** `/home/kasadis/summitflow/backend/app/services/agent_hub.py`

**Entry Points:**
- `st autocode <task_id> --sync`
- POST `/projects/{project_id}/tasks/{task_id}/autocode`

**Legacy Issues:**
```python
# Single-turn generate() - NOT agentic run_agent()
response = client.generate(
    prompt=prompt,
    system=system_prompt,
    temperature=0.7,
    purpose="code_generation",
)

# Expects JSON "evidence contract" from agent
# Agent must output specific JSON format:
{
  "status": "completed",
  "files": [{"path": "...", "content": "..."}],
  "commands": [...],
  "verifications": [...]
}
```

**Problems:**
- Single-turn: agent can't iterate, use tools, or recover from errors
- Evidence contract: requires agent to self-report (unverifiable)
- No verify_command: doesn't run actual verification commands
- No memory injection: mandates/guardrails not applied
- Writes files directly: no worktree isolation

**Migration Path:**
- Remove `--sync` flag from CLI
- Remove `/autocode` endpoint or redirect to async flow
- Delete `services/agent_hub.py` (AgentHubService class)

---

### 4. Agent Runner ❌ REMOVE
**Location:** `/home/kasadis/summitflow/backend/app/tasks/agent_runner.py`

**Entry Points:**
- POST `/{project_id}/tasks/{task_id}/start`
- Internal `run_agent_task.delay()`

**Issues:**
```python
# Very basic - just calls generate() and marks complete
response = agent.generate(
    prompt=context,
    system=_get_system_prompt(project_id),
)
tasks.update_task_status(task_id, "completed")  # Always marks complete!
```

**Problems:**
- No subtask handling
- No verification
- No worktree isolation
- Just marks task "completed" after any response
- 5-minute timeout (too short for real work)

**Migration Path:**
- Remove `/start` endpoint
- Remove `run_agent_task` Celery task
- This was likely early prototyping

---

### 5. Implementation Executor ❌ REMOVE (Already Orphaned)
**Location:** `/home/kasadis/summitflow/backend/app/api/implementation.py`

**Entry Points:**
- POST `/{project_id}/tasks/{task_id}/execute/start`
- POST `/{project_id}/tasks/{task_id}/execute/next`
- GET `/{project_id}/tasks/{task_id}/execute/status`
- POST `/{project_id}/tasks/{task_id}/execute/resume`

**Status:** **ORPHANED** - endpoints exist but nothing calls them:
- Not called from CLI
- Not called from frontend
- Not called from any other backend code
- Only referenced in integration tests

**Migration Path:**
- Delete `app/api/implementation.py`
- Delete related test files
- Clean up any remaining references

---

## Entry Point Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        st autocode <task_id>                        │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ├── (default, no --sync)
                            │   │
                            │   ▼
                            │   Set status = "queue"
                            │   │
                            │   ▼
                            │   _dispatch_autonomous_task()
                            │   │
                            │   ▼
                            │   ┌─────────────────────────────────────┐
                            │   │   autonomous.start_execution()     │ ✅ CORRECT
                            │   │   - run_agent() with agent_slug    │
                            │   │   - verify_step() verification     │
                            │   │   - memory injection enabled       │
                            │   │   - fresh context per subtask      │
                            │   └─────────────────────────────────────┘
                            │
                            └── (--sync flag)
                                │
                                ▼
                                POST /autocode API
                                │
                                ▼
                                ┌─────────────────────────────────────┐
                                │   AgentHubService.dispatch_task()  │ ❌ LEGACY
                                │   - generate() single-turn         │
                                │   - evidence contract parsing      │
                                │   - no verification                │
                                └─────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│              POST /projects/{}/tasks/{}/execute                     │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                ┌─────────────────────────────────────┐
                │   execute_orchestrator_task()      │ ❌ LEGACY
                │   - run_agent() with provider/model │
                │   - heuristic text parsing         │
                │   - no agent_slug, no memory       │
                └─────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│              POST /{}/tasks/{}/start                                │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                ┌─────────────────────────────────────┐
                │   run_agent_task()                 │ ❌ LEGACY
                │   - generate() single-turn         │
                │   - marks complete immediately     │
                │   - no verification                │
                └─────────────────────────────────────┘
```

---

## Files to Remove/Modify

### Remove Entirely
- `backend/app/api/implementation.py` - orphaned endpoints
- `backend/app/services/agent_hub.py` - AgentHubService (evidence contract)
- `backend/app/tasks/agent_runner.py` - basic runner
- `backend/app/services/orchestrator/` - entire directory

### Modify
- `backend/cli/commands/tasks.py` - remove `--sync` flag from autocode
- `backend/app/api/tasks/autocode.py` - remove sync endpoint or redirect
- `backend/cli/_client_execution.py` - remove `start_execution()` function

### Keep (Production Code)
- `backend/app/tasks/autonomous/` - entire directory
- `backend/app/tasks/autonomous/execution.py` - main execution
- `backend/app/tasks/autonomous/verification.py` - verify_step()
- `backend/app/tasks/autonomous/escalation.py` - 3-2-1 pattern
- `backend/app/tasks/autonomous/review.py` - AI review
- `backend/app/tasks/autonomous/planning.py` - plan generation
- `backend/app/tasks/autonomous/triage.py` - idea triage

---

## Migration Checklist

### Phase 1: Preparation
- [ ] Verify Autonomous pipeline is working in production
- [ ] Document any unique features in legacy workflows
- [ ] Create feature flags if gradual migration needed

### Phase 2: Add Missing Features to Autonomous
- [ ] Add pristine codebase check (from Orchestrator)
- [ ] Add chat message context support if needed
- [ ] Verify WebSocket streaming works correctly

### Phase 3: Remove Legacy Code
- [ ] Remove `--sync` flag from `st autocode`
- [ ] Remove `/autocode` endpoint (or redirect to queue-based)
- [ ] Remove `/execute` endpoint
- [ ] Remove `/start` endpoint
- [ ] Delete orphaned files (see list above)
- [ ] Update tests that reference removed code

### Phase 4: Cleanup
- [ ] Remove unused imports
- [ ] Update documentation
- [ ] Archive this audit document

---

## Appendix: Code Locations

### Autonomous (KEEP)
```
backend/app/tasks/autonomous/
├── __init__.py
├── execution.py      # start_execution() - main entry
├── verification.py   # verify_step()
├── escalation.py     # 3-2-1 pattern
├── review.py         # ai_review()
├── planning.py       # create_plan()
├── triage.py         # triage_idea()
├── ideas.py          # process_crowdsourced_ideas()
└── pickup.py         # autonomous_work_pickup()
```

### Orchestrator (REMOVE)
```
backend/app/services/orchestrator/
├── __init__.py       # OrchestratorService
├── coordination.py   # do_coordinate()
├── execution.py      # dispatch_to_worker()
├── handlers.py       # failure/PR handlers
├── types.py          # ExecutionState, etc.
└── websocket.py      # WebSocket mixin
```

### Agent Hub Service (REMOVE)
```
backend/app/services/agent_hub.py  # AgentHubService.dispatch_task()
```

### Agent Runner (REMOVE)
```
backend/app/tasks/agent_runner.py  # run_agent_task()
```

### Implementation (REMOVE)
```
backend/app/api/implementation.py  # Orphaned endpoints
```
