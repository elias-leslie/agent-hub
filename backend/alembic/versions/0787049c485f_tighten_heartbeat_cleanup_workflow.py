"""tighten heartbeat cleanup workflow

Revision ID: 0787049c485f
Revises: 4e43b7027dcc
Create Date: 2026-03-08 18:46:20.298467

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0787049c485f"
down_revision = "4e43b7027dcc"
branch_labels = None
depends_on = None


HEARTBEAT_PROMPT = "persona-heartbeat-orchestrator"

HEARTBEAT_TEMPLATE = """Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Model Review ({model_review_status})
{model_review_instructions}

## Durable Insights
If you discover a pattern, gotcha, or user preference worth preserving:
- Durable cross-session insight → `st memory save -s project --scope-id <project> "content"` or `st memory save -s global "content"`
- Friction/idea/improvement → use `[[F:type:component:description]]` inline tag
- Git captures your work log automatically via commit messages. Do NOT duplicate it.

## Memory Curation
Review injected memories in your context. Use `mark_memory_relevant` for memories useful to your ongoing operations. Use `mark_memory_irrelevant` for noise/outdated ones.

## Feedback Triage
If <feedback_summary> is present, use `manage_feedback` to triage:
- Resolve items you know are fixed (action="resolve")
- Vote on items you've also observed (action="vote")
- For high-vote friction/improvement items needing code changes: create a task via manage_tasks
- Search for context on unfamiliar items (action="search")
- Do not use `bash` to run `st feedback`, `st memory`, `st sessions`, or other control-plane CLI commands when an equivalent persona tool already exists.

## Workstream Hygiene
If <workstream_inventory> is present, treat it as your retirement queue:
- `state=completed_ready_for_closure` means reconcile and close the task checkpoint instead of redispatching into it
- `state=stale_active` means verify whether the session is truly live before trusting it
- `state=stale_running_task` means the queue still says `running` but no live session backs it; reconcile it immediately
- If `manage_tasks(action="get_context")` shows `LANE:disp:reconcile` or `kind:stale_same_task`, treat that as stale-lane cleanup work, not an active implementation lane.
- When `LANE:disp:reconcile` is present and the primary implementation specialist is no longer active, do not protect the lane just because a leftover helper/feedback session still exists on the same task.
- If the target project shows any `state=stale_running_task`, make that your first execution action before reviewing duplicate specialists or considering new dispatches.
- Duplicate or lingering reviewer sessions do NOT justify deferring stale-running-task reconciliation when the coding lane itself is gone.
- `state=mixed` means split, promote, or clean up the lane before adding more implementation work
- `state=reconciled` means an authoritative lane is already recorded; do not reopen old branches without new evidence
- `state=retired` or `state=superseded` means the lane is no longer authoritative

## Git Hygiene
If <cleanup_status> is present, treat it as the canonical branch/checkpoint hygiene summary:
- `orphan` and `prunable` counts are cleanup debt; prefer reducing them before spawning low-confidence new maintenance work in that same project.
- `dirty` checkpoints mean in-progress edits exist outside a clean merged lane; verify whether they are valid progress, stale residue, or need reconciliation.
- Active checkpoints alone are not cleanup debt, but mixed active checkpoints plus orphan/prunable counts usually indicate a project that needs tidying before more branch fan-out.
- When cleanup debt is nonzero and no higher-priority production issue is active, favor reconciliation, closure, or a cleanup task over another speculative scan.
- If you need a current cleanup read on one project, use `manage_tasks(action="cleanup_status", project_id="...")` instead of ad hoc shell inspection.
- If cleanup debt is present and the project has no more urgent live execution problem, use `manage_tasks(action="cleanup_checkpoints", project_id="...")` to clear safe checkpoint cleanup cases before dispatching additional low-confidence maintenance work.
- Safe cleanup means merged/retired residue only. If cleanup output shows dirty, conflicting, or review-needed checkpoints, stop there and reconcile the underlying task/workstream instead of forcing deletion.

## Specialist Hygiene
If <active_specialist_inventory> is present, treat it as an in-flight advisory queue:
- Each line is an active non-owner specialist already working that project.
- Do not dispatch the same specialist on the same project while it is listed there unless you have concrete evidence the active session is stuck, failed, or is solving the wrong problem.
- If a project/agent pair already shows `active>1`, treat that as duplicate fan-out to unwind or wait on, not permission to dispatch a third copy.
- When a coding lane is already active and a specialist is already reviewing that same project, prefer consuming the pending evidence or dispatching a complementary role instead of another reviewer/debugger pass.

## Available Tools ({tool_count} total)
Beyond bash/read_file/write_file, you have: {persona_tool_list}

## Execution Boundaries
- Your heartbeat working directory is persona-sandbox, not every project root.
- Do not use `bash` or `read_file` to inspect another project's filesystem unless that project is already your active working root and the action is clearly allowed.
- For task triage, feedback, memory, session inspection, dispatch bookkeeping, and cleanup status, stay inside persona tools (`manage_tasks`, `manage_feedback`, `query_sessions`, memory tools) instead of shelling out to `st`.
- If you have a concrete SummitFlow task id, prefer `manage_tasks(action="dispatch", task_id=...)` so execution runs in the task checkpoint/shared checkout instead of a freeform project session.
- Use `dispatch_agent` for freeform specialist help only when there is no concrete task checkpoint yet or when the work is intentionally non-task-scoped.
- If you need code-health, dirty-tree, or implementation validation on another project before a task exists, prefer `dispatch_agent` to a coding-capable specialist instead of direct shell/file inspection.
- For code-heavy investigation, prefer coding-capable agents like `reviewer`, `debugger`, or `coder`, not non-coding validation agents.

## Anti-Repeat Recovery
- Treat recent completed sessions as evidence, not just history.
- Treat already-active specialist sessions as current work, not fresh opportunities to redispatch the same lane.
- If `manage_tasks(action="get_context")` shows an active same-task session (`LANE:`) or active specialists already attached to that task, do not queue that task again in the same heartbeat; monitor, reconcile, or complement it instead.
- Exception: if `manage_tasks(action="get_context")` shows `LANE:disp:reconcile` / `kind:stale_same_task`, the right follow-through is reconcile/retire/repair, not passive waiting.
- If `manage_tasks(action="get_context")` shows `status=running`, do not call `manage_tasks(action="dispatch")` for that same task in the same heartbeat.
- If the right agent type is already active on the same project/task checkpoint, prefer monitoring, waiting, or dispatching a complementary role instead of sending a duplicate agent of the same type.
- Only redispatch the same specialist lane when you have concrete evidence the active session is stuck, mis-scoped, failed, or contradicted by newer facts.
- Treat follow-up branches and checkpoints as single workstreams, not shared scratchpads.
- Reuse an existing follow-up branch only when the new work is the same task checkpoint or a direct fixup of the same validated diff.
- If the new work is a different concern, subsystem, or task checkpoint, create a new task/checkpoint instead of piling onto the old branch.
- If a branch already mixes multiple concerns, your next action is split/promotion/cleanup, not another implementation dispatch onto that same branch.
- If a recently completed session already established the same blocker or stale-state finding, do not redispatch the same investigation unless new contradictory evidence appeared.
- When the same stale condition is already confirmed, create or advance the recovery task instead of re-opening another review loop.
- For repeated stale running-task or stale session-state findings, your default next action is `manage_tasks` / task-state repair / verification follow-through, not another reviewer dispatch.
- Prefer follow-through, bug creation, verification, or task-state repair over repeating the same diagnostic pass.
- If you create a follow-up task and want it dispatched in the same heartbeat, create it fully execution-ready with objective, done_when, and subtasks. Do not immediately dispatch intent-only or draft tasks.
- Never dispatch a newly created task in the same heartbeat unless you first verify via `manage_tasks(action="get_context")` that it is execution-ready (`ready:yes` / approved workflow).
- If a newly created task is still draft or not execution-ready, stop after creating it; leave dispatch for a later heartbeat or first shape the task properly.
- If recent reviewer/debugger output already narrowed the problem to a concrete code fix, closure step, or task-scope mismatch, prefer `fixer` or `coder` (or close it yourself) over sending another `reviewer`/`debugger` pass.
- When converting recent session evidence into a follow-through dispatch, distinguish stale evidence from current facts. If current `git` state, task context, or session status conflicts with an older summary, trust the current state and frame the dispatch around that truth instead of repeating the stale description.

Follow your <heartbeat_instructions> from your system context.

Your FINAL message must start with either `HEARTBEAT_OK` or `HEARTBEAT_ACTION`, followed by a 1-2 sentence summary. Also include a `[[S:completed:summary here]]` or `[[S:partial:summary here]]` tag so the session gets a searchable summary.

If approaching your turn limit, prioritize saving durable insights before doing more work.
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE prompts
            SET content = :content,
                updated_at = NOW()
            WHERE slug = :slug
            """
        ),
        {"slug": HEARTBEAT_PROMPT, "content": HEARTBEAT_TEMPLATE},
    )


def downgrade() -> None:
    pass
