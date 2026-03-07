"""Heartbeat prompt string constants and model-review text."""

from __future__ import annotations

HEARTBEAT_PROMPT_TEMPLATE = """\
Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Model Review ({model_review_status})
{model_review_instructions}

## Durable Insights
If you discover a pattern, gotcha, or user preference worth preserving:
- Durable cross-session insight → `st memory save -s project --scope-id <project> "content"` or `st memory save -s global "content"`
- Friction/idea/improvement → use `[[F:type:component:description]]` inline tag
- Git captures your work log automatically via commit messages. Do NOT duplicate it.

## Memory Curation
Review injected memories in your context. Use `mark_memory_relevant` for memories \
useful to your ongoing operations. Use `mark_memory_irrelevant` for noise/outdated ones.

## Feedback Triage
If <feedback_summary> is present, use `manage_feedback` to triage:
- Resolve items you know are fixed (action="resolve")
- Vote on items you've also observed (action="vote")
- For high-vote friction/improvement items needing code changes: create a task via manage_tasks
- Search for context on unfamiliar items (action="search")

## Workstream Hygiene
If <workstream_inventory> is present, treat it as your retirement queue:
- `state=completed_ready_for_closure` means reconcile and close the task lane instead of redispatching into it
- `state=stale_active` means verify whether the session is truly live before trusting it
- `state=stale_running_task` means the queue still says `running` but no live lane backs it; reconcile it immediately
- `state=mixed` means split, promote, or clean up the lane before adding more implementation work
- `state=reconciled` means an authoritative lane is already recorded; do not reopen old branches without new evidence
- `state=retired` or `state=superseded` means the lane is no longer authoritative

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
- If you need code-health, dirty-tree, or implementation validation on another project, prefer `dispatch_agent` to a coding-capable specialist instead of direct shell/file inspection.
- For code-heavy investigation, prefer coding-capable agents like `reviewer`, `debugger`, or `coder`, not non-coding validation agents.

## Anti-Repeat Recovery
- Treat recent completed sessions as evidence, not just history.
- Treat already-active specialist sessions as current work, not fresh opportunities to redispatch the same lane.
- If the right agent type is already active on the same project/task lane, prefer monitoring, waiting, or dispatching a complementary role instead of sending a duplicate agent of the same type.
- Only redispatch the same specialist lane when you have concrete evidence the active session is stuck, mis-scoped, failed, or contradicted by newer facts.
- Treat follow-up branches and worktrees as single workstreams, not shared scratchpads.
- Reuse an existing follow-up branch only when the new work is the same task lane or a direct fixup of the same validated diff.
- If the new work is a different concern, subsystem, or task lane, create a new task/worktree instead of piling onto the old branch.
- If a branch already mixes multiple concerns, your next action is split/promotion/cleanup, not another implementation dispatch onto that same branch.
- If a recently completed session already established the same blocker or stale-state finding, do not redispatch the same investigation unless new contradictory evidence appeared.
- When the same stale condition is already confirmed, create or advance the recovery task instead of re-opening another review loop.
- For repeated stale running-task or stale session-state findings, your default next action is `manage_tasks` / task-state repair / verification follow-through, not another reviewer dispatch.
- Prefer follow-through, bug creation, verification, or task-state repair over repeating the same diagnostic pass.
- If recent reviewer/debugger output already narrowed the problem to a concrete code fix, closure step, or task-scope mismatch, prefer `fixer` or `coder` (or close it yourself) over sending another `reviewer`/`debugger` pass.
- When converting recent session evidence into a follow-through dispatch, distinguish stale evidence from current facts. If current `git` state, task context, or session status conflicts with an older summary, trust the current state and frame the dispatch around that truth instead of repeating the stale description.

Follow your <heartbeat_instructions> from your system context.

Your FINAL message must start with either `HEARTBEAT_OK` or `HEARTBEAT_ACTION`, \
followed by a 1-2 sentence summary. Also include a `[[S:completed:summary here]]` \
or `[[S:partial:summary here]]` tag so the session gets a searchable summary.

If approaching your turn limit, prioritize saving durable insights before doing more work.\
"""

MODEL_REVIEW_DO = (
    "Due — run `review_agent_performance` + `manage_model_config(action=get_benchmarks)` + "
    "`manage_model_config(action=list_agents)`. Check `synced_at` — if benchmark data >60 days old, "
    "`send_push` to flag stale benchmarks. Evaluate model assignments. Log via `log_agent_performance`."
)
MODEL_REVIEW_SKIP = "Not due — skip model review this heartbeat."

__all__ = [
    "HEARTBEAT_PROMPT_TEMPLATE",
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
]
