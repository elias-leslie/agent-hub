"""Compact text views of a durable workflow run: one line per step, then the run totals."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

FINISHED_RUN_STATES = ("completed", "failed", "cancelled")
# Step statuses that end a step for good (a step "needs_owner" or "pending" can still move).
FINISHED_STEP_STATUSES = ("completed", "skipped", "cancelled", "failed", "refused")


def _age(iso: str | None, now: datetime | None = None) -> str | None:
    """How long ago an ISO timestamp was, as "12s", "4m" or "2h"."""
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = max(int(((now or datetime.now(UTC)) - then).total_seconds()), 0)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{round(seconds / 60)}m"
    return f"{round(seconds / 3600)}h"


def _usd(value: Any) -> str:
    return f"${value:.4f}" if isinstance(value, int | float) else "$?"


def last_attempt(step: dict[str, Any]) -> dict[str, Any] | None:
    history = step.get("attempt_history") or []
    return history[-1] if history else None


def _bare(model: str) -> str:
    """The model without provider prefix, case or dated snapshot: the same rule the server uses for a model switch."""
    return re.sub(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$", "", model.strip().lower().rsplit("/", 1)[-1])


def model_text(step: dict[str, Any]) -> str:
    """"requested→served" once an attempt has run (just the model when they match), else the model it will start on."""
    attempt = last_attempt(step)
    requested = (attempt or {}).get("requested_model") or (attempt or {}).get("effective_model")
    served = (attempt or {}).get("served_model")
    if not requested and not served:  # not started, or the attempt has not named its model yet
        chain = step.get("chain") or []
        return str(step.get("chosen_model") or (chain[0] if chain else "-"))
    requested = requested or "-"
    if served and requested != "-" and _bare(served) != _bare(requested):
        return f"{requested}→{served}"
    return str(served or requested)


def outcome_text(step: dict[str, Any]) -> str | None:
    """Fallback and last-attempt outcome, e.g. "fallback(usage_limit) acceptance_failed"."""
    parts: list[str] = []
    attempt = last_attempt(step)
    if attempt and attempt.get("fallback_used"):
        parts.append(f"fallback({attempt.get('fallback_reason') or '?'})")
    outcome = step.get("outcome") or {}
    reason = outcome.get("reason") or ((attempt or {}).get("decision") or {}).get("reason")
    if reason and step.get("status") != "pending":
        parts.append(str(reason))
    if outcome.get("error") and step.get("status") in ("failed", "refused", "needs_owner"):
        parts.append(f"error={str(outcome['error'])[:80]!r}")
    return " ".join(parts) or None


def cost_text(step: dict[str, Any]) -> str | None:
    """Cost summed per basis across attempts; an attempt without a price shows "$?", never zero."""
    by_basis: dict[str, float | None] = {}
    for attempt in step.get("attempt_history") or []:
        if attempt.get("status") == "active" and not attempt.get("usage"):
            continue  # still running: no usage reported yet, which is not the same as unpriced
        cost = attempt.get("cost") or {}
        basis = cost.get("basis") or "unknown"
        usd = cost.get("usd")
        if usd is None:
            by_basis.setdefault(basis, None)
        else:
            by_basis[basis] = (by_basis.get(basis) or 0.0) + usd
    if not by_basis:
        return None
    return ", ".join(f"{_usd(usd)} {basis}" for basis, usd in by_basis.items())


def tools_text(step: dict[str, Any]) -> str | None:
    """The tool names the last attempt was given ("tools=none" when it had none), when its executor reported them."""
    tools = (last_attempt(step) or {}).get("tools")
    if tools is None:
        return None
    names = [str(t) for t in tools]
    shown = ",".join(names[:8]) + (f"+{len(names) - 8}" if len(names) > 8 else "")
    return f"tools={shown or 'none'}"


def live_text(step: dict[str, Any], now: datetime | None = None) -> str | None:
    live = step.get("live")
    if step.get("status") != "running" or not live:
        return None
    text = f"live={live.get('phase') or '?'}"
    age = _age(live.get("last_event_at"), now)
    text += f" last={age} ago" if age else " last=no event yet"
    if live.get("harness_alive") is False:
        text += " HARNESS-GONE"
    return text


def step_line(step: dict[str, Any], now: datetime | None = None) -> str:
    cells = [f"{step.get('key')}", f"{step.get('status')}", model_text(step)]
    if extra := outcome_text(step):
        cells.append(extra)
    cells.append(f"attempt {step.get('attempts', 0)}/{step.get('attempt_limit', '?')}")
    if tools := tools_text(step):
        cells.append(tools)
    if live := live_text(step, now):
        cells.append(live)
    if step.get("cancelling"):
        cells.append("cancelling")
    readiness = step.get("readiness")
    if readiness and readiness.get("state") != "ready" and readiness.get("reason"):
        cells.append(str(readiness["reason"]))
    if cost := cost_text(step):
        cells.append(cost)
    return "  " + " | ".join(cells)


def totals_text(view: dict[str, Any]) -> str:
    totals = view.get("usage_totals") or {}
    cost = totals.get("cost") or {}
    parts = []
    for basis, row in (cost.get("by_basis") or {}).items():
        attempts = row.get("attempts") or 0
        if attempts:
            parts.append(f"{_usd(row.get('usd'))} {basis} ({attempts} attempt{'s' if attempts != 1 else ''})")
    if cost.get("unpriced_attempts"):
        parts.append(f"{cost['unpriced_attempts']} unpriced")
    spent = "; ".join(parts) or "no usage yet"
    return f"totals: {totals.get('total_tokens') or 0:,} tokens; cost {spent}"


def pause_text(pause: dict[str, Any] | None) -> str | None:
    """The decision the run waits for, e.g. "chain_exhausted step=build"."""
    if not pause:
        return None
    detail = " ".join(
        f"{k}={v}" for k, v in pause.items() if k not in ("at", "reason", "waiting") and v not in (None, "", [], {})
    )
    text = f"{pause.get('reason', 'paused')}" + (f" {detail}" if detail else "")
    waiting = pause.get("waiting") or {}
    if len(waiting) > 1:  # the fields above are the first; every step waiting on the owner is listed once
        text += " | waiting: " + ", ".join(f"{k} ({(v or {}).get('reason', '?')})" for k, v in waiting.items())
    return text


def counts_text(view: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for step in view.get("steps") or []:
        counts[step.get("status", "?")] = counts.get(step.get("status", "?"), 0) + 1
    return ", ".join(f"{n} {status}" for status, n in counts.items()) or "no steps"


def run_header(view: dict[str, Any], page_url: str | None = None) -> list[str]:
    head = f"run {view.get('id')} {view.get('state')} | plan r{view.get('plan_revision', 0)} | {counts_text(view)}"
    lines = [head, f"  goal: {view.get('goal')}"]
    who = [f"{k}={view[k]}" for k in ("launched_by", "coordinator") if view.get(k)]
    if who:
        lines.append("  " + " ".join(who))
    if view.get("tool_level"):
        lines.append(f"  tool level: {view['tool_level']}")
    if pause := pause_text(view.get("pause")):
        lines.append(f"  needs owner: {pause}")
    if view.get("failure"):
        lines.append(f"  failure: {view['failure']}")
    if view.get("cancel"):
        reason = (view["cancel"] or {}).get("reason")
        lines.append(f"  cancel requested{f': {reason}' if reason else ''}" + (" (stopping)" if view.get("cancelling") else ""))
    if page_url:
        lines.append(f"  page: {page_url}")
    return lines


def run_text(view: dict[str, Any], page_url: str | None = None, now: datetime | None = None) -> str:
    lines = run_header(view, page_url)
    lines += [step_line(step, now) for step in view.get("steps") or []]
    lines.append(totals_text(view))
    return "\n".join(lines)


def list_line(row: dict[str, Any]) -> str:
    counts = ", ".join(f"{n} {s}" for s, n in (row.get("step_counts") or {}).items()) or "no steps"
    goal = str(row.get("goal") or "")
    goal = goal if len(goal) <= 70 else goal[:69] + "…"
    mine = row.get("launched_by") or "-"
    return f"{row.get('id')} | {row.get('state')} | {counts} | {mine} | {goal}"
