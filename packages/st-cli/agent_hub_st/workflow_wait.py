"""Wait on a durable workflow run by polling its view: what changed, and a distinct exit code per end condition.

The runner has no events endpoint, so this is one cheap GET per interval with backoff that resets on change.
Waiting never ends because time passed: only ``max_wait`` (an explicit caller choice) returns control early, and it
cancels nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import typer

from .workflow_format import (
    FINISHED_RUN_STATES,
    FINISHED_STEP_STATUSES,
    model_text,
    outcome_text,
    pause_text,
    run_text,
)

# Exit codes, one per way a wait can end. 0 is the run finishing; 1 and 2 keep their usual error / usage meanings.
EXIT_DONE = 0
EXIT_ERROR = 1
EXIT_NEEDS_OWNER = 10
EXIT_FAILED = 11
EXIT_CANCELLED = 12
EXIT_STEP_ENDED = 13  # the awaited step ended without completing (failed, refused, cancelled)
EXIT_STEP_DONE = 20  # the awaited step completed or was skipped
EXIT_CHANGED = 21
EXIT_MAX_WAIT = 30  # the caller's --max-wait passed; the run is untouched and still going
EXIT_LOST_CONTACT = 31  # Agent Hub stopped answering; the run is held by the runner and can be re-attached

EXIT_CODES_HELP = (
    "Exit codes: 0 run completed, 10 needs owner decision, 11 run failed, 12 run cancelled, "
    "13 awaited step ended without completing, 20 awaited step done, 21 something changed, "
    "30 --max-wait passed (run still going), 31 lost contact, 1 error."
)

# A pause the runner clears by itself when a usage limit resets: nothing for the coordinator to decide.
SELF_RESUMING_PAUSES = ("usage_limit_wait",)

Fetch = Callable[[], dict[str, Any]]


def parse_until(value: str) -> tuple[str, str | None]:
    """("done" | "needs_owner" | "any-change", None) or ("step", key)."""
    if value in ("done", "needs_owner", "any-change"):
        return value, None
    if value.startswith("step:") and value[5:]:
        return "step", value[5:]
    raise typer.BadParameter("use done, needs_owner, any-change or step:<key>")


def needs_decision(view: dict[str, Any]) -> bool:
    """Whether any pause reason needs the owner: the top-level one and every entry of the ``waiting`` map."""
    pause = view.get("pause") or {}
    if view.get("state") != "needs_owner":
        return False
    reasons = [pause.get("reason")]
    reasons += [(entry or {}).get("reason") for entry in (pause.get("waiting") or {}).values()]
    return any(reason not in SELF_RESUMING_PAUSES for reason in reasons)


def snapshot(view: dict[str, Any]) -> dict[str, Any]:
    """What counts as a change: run state and pause, the plan, and each step's status, attempts, model and outcome.

    Live phase and last-activity time move constantly and are left out; ``st workflow get`` shows them.
    """
    steps = {}
    for step in view.get("steps") or []:
        readiness = step.get("readiness") or {}
        steps[step["key"]] = {
            "status": step.get("status"),
            "attempts": step.get("attempts"),
            "model": model_text(step),
            "outcome": outcome_text(step),
            "ready": readiness.get("state"),
            "cancelling": bool(step.get("cancelling")),
        }
    return {
        "state": view.get("state"),
        "pause": pause_text(view.get("pause")),
        "plan_revision": view.get("plan_revision", 0),
        "cancelling": bool(view.get("cancelling")),
        "steps": steps,
    }


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Plain lines describing what moved between two snapshots."""
    lines: list[str] = []
    if old["state"] != new["state"]:
        extra = f" ({new['pause']})" if new["pause"] else ""
        lines.append(f"run: {old['state']} → {new['state']}{extra}")
    elif old["pause"] != new["pause"]:
        lines.append(f"run: pause {old['pause'] or '-'} → {new['pause'] or '-'}")
    if old["plan_revision"] != new["plan_revision"]:
        lines.append(f"plan: revision {old['plan_revision']} → {new['plan_revision']}")
    if not old["cancelling"] and new["cancelling"]:
        lines.append("run: cancelling")
    for key, step in new["steps"].items():
        before = old["steps"].get(key)
        if before is None:
            lines.append(f"step {key}: added ({step['status']})")
            continue
        notes = []
        if before["status"] != step["status"]:
            notes.append(f"{before['status']} → {step['status']}")
        if before["attempts"] != step["attempts"]:
            notes.append(f"attempt {step['attempts']}")
        if before["model"] != step["model"]:
            notes.append(f"model {step['model']}")
        if before["outcome"] != step["outcome"] and step["outcome"]:
            notes.append(step["outcome"])
        if before["ready"] != step["ready"] and step["status"] == "pending":
            notes.append(f"{step['ready'] or 'not pending'}")
        if not before["cancelling"] and step["cancelling"]:
            notes.append("cancelling")
        if notes:
            lines.append(f"step {key}: " + ", ".join(notes))
    lines += [f"step {key}: removed" for key in old["steps"] if key not in new["steps"]]
    return lines


def _run_end(view: dict[str, Any]) -> int | None:
    """The exit code when the run itself reached an end every wait stops at (finished, or paused for a decision)."""
    state = view.get("state")
    if state in FINISHED_RUN_STATES:
        return {"completed": EXIT_DONE, "failed": EXIT_FAILED, "cancelled": EXIT_CANCELLED}[state]
    if needs_decision(view):
        return EXIT_NEEDS_OWNER
    return None


def end_code(kind: str, key: str | None, view: dict[str, Any], baseline: dict[str, Any] | None) -> tuple[int | None, str]:
    """(exit code, why) when the wait is over for this view, else (None, "")."""
    if kind == "step":
        step = next((s for s in view.get("steps") or [] if s.get("key") == key), None)
        if step is not None and step.get("status") in FINISHED_STEP_STATUSES:
            ok = step["status"] in ("completed", "skipped")
            return (EXIT_STEP_DONE if ok else EXIT_STEP_ENDED), f"step {key} {step['status']}"
        if step is None and view.get("state") in FINISHED_RUN_STATES:
            return EXIT_ERROR, f"step {key} is not in this run"
    elif kind == "any-change" and baseline is not None and snapshot(view) != baseline:
        return EXIT_CHANGED, "changed"
    code = _run_end(view)
    if code is None:
        return None, ""
    return code, f"run {view.get('state')}"


def wait_for(
    fetch: Fetch,
    until: str,
    *,
    emit: Callable[[str], None],
    page_url: str | None = None,
    poll_min: float = 2.0,
    poll_max: float = 10.0,
    max_wait: float | None = None,
    max_errors: int = 12,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Poll until ``until`` holds; print each change; return the exit code for how it ended."""
    kind, key = parse_until(until)
    started = clock()
    interval = poll_min
    errors = 0
    view = fetch()  # the first read is strict: a missing run or bad address fails right away
    seen = snapshot(view)
    emit(f"waiting for {until}: {run_text(view, page_url, now() if now else None).splitlines()[0]}")
    baseline = seen if kind == "any-change" else None
    while True:
        code, why = end_code(kind, key, view, baseline)
        if code is not None:
            emit(f"{why}")
            emit(run_text(view, page_url, now() if now else None))
            if code == EXIT_NEEDS_OWNER:
                emit("next: st workflow resume <id> --action retry|skip|fail, or revise/add-step first")
            return code
        if max_wait is not None and clock() - started >= max_wait:
            emit(f"max-wait reached; the run is untouched and still {view.get('state')}")
            return EXIT_MAX_WAIT
        sleep(interval)
        try:
            view = fetch()
            errors = 0
        except typer.Exit:
            errors += 1
            if errors >= max_errors:
                emit(f"lost contact with Agent Hub after {errors} failed reads; the run is held by the runner, re-attach with st workflow wait")
                return EXIT_LOST_CONTACT
            interval = min(interval * 1.5, poll_max)
            continue
        current = snapshot(view)
        if current != seen:
            for line in diff(seen, current):
                emit(line)
            seen = current
            interval = poll_min
        else:
            interval = min(interval * 1.5, poll_max)
