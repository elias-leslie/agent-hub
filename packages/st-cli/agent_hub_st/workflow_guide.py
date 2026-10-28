"""How a coordinator drives a durable workflow run. Shown on demand with `st tools manifest --surface st.workflow`."""

from __future__ import annotations

GUIDE: tuple[str, ...] = (
    "The runner holds all job state; your chat can end and re-attach. Create with --request-id (a stable name) so a second create returns the same run; re-attach later with st workflow list --mine, get or wait.",
    "Plan: one step per deliverable, each with key, instructions that stand alone (a step sees only its dependencies' handoffs), agent_slug, and acceptance commands the runner executes in the step's worktree (exit 0 = done). No acceptance command means nothing checks the step.",
    "Dependencies: depends_on lists the steps a step needs; omitted means the step before it, [] means none. Independent steps can run side by side where the run's max_concurrent_steps allows.",
    "Models: set model_override and a narrow allowed_models per step; the agent's chain supplies fallbacks. Cheap model for mechanical edits, strongest for design or review. Pick executor and effort per step when the default does not fit. Check usage limits before choosing a harness.",
    "st workflow create --file def.json [--request-id ID] prints the run id and page URL; AICO session and agent fill launched_by and coordinator.",
    "st workflow wait ID --until done blocks without any time limit and prints what changed. It stops at a finished run or a pause that needs a decision. Use any-change to react to each change, step:KEY to continue as soon as one step ends. --max-wait only returns control to you; it cancels nothing.",
    "Wait exit codes: 0 completed, 10 needs owner, 11 failed, 12 cancelled, 13 awaited step ended without completing, 20 awaited step done, 21 changed, 30 --max-wait passed, 31 lost contact.",
    "On 10: st workflow get ID shows the pause reason and step. Fix the cause, then resume: retry (optionally --extra-attempts N when the step used its attempts), skip, or fail. Revise the step first if instructions, acceptance or model were wrong.",
    "Revise a step only while pending: st workflow revise ID KEY --set model_override=MODEL --set max_attempts=3 --reason WHY (values are JSON or text; null clears). A step that already started answers 409; cancel it with --step KEY and add a replacement.",
    "As you learn, add-step --file step.json [--after KEY] extends the plan, also after the run completed; remove-step drops a pending step nothing depends on. Plan changes are kept in the run's history with your reason.",
    "Read st workflow get ID before deciding: requested→served model shows silent fallbacks, attempt n/N the budget left, cost basis separates metered spend from subscription-equivalent. Unpriced shows $?, which is unknown, not zero.",
    "End: let the run finish, or st workflow cancel ID [--step KEY] --reason WHY; cancelling stops running work and keeps the finished steps' commits and history. Never cancel just because waiting is long.",
)
