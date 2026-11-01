"""Nightshift items for context: one rolling review item and one budget item per cell over its level.

Both go to the tray and the board, never the phone (push "tray"). Each is one live item per key:
  - agent-hub-context-review: pushed when the review queue goes from empty to N, refreshed once per Nightshift
    STALE_S while it stays non-empty (an open warning nothing newer touched for that long shows as unknown), resolved
    at 0. Nightshift logs a repeat under a key whose item is still open as `tray` (no second card), so the refresh
    is quiet; it is still not sent on every change.
  - agent-hub-context-budget:<harness>:<cell>: sent when the cell goes over, refreshed the same way. It resolves only
    when the cell is clearly back under (budgets: below 90% of the warn level, below half of jump_pct); in between it
    stays open, and with too little data to judge it keeps whatever state it had. The text names the cause (`why`
    over the window that tripped it, not an old step) and only a knob that changed.
What was sent, and when, is kept in subscription_usage_cursors rows named @context_alert:<key>. Every send is
committed at once (a later failure cannot make the next pass send it again), under a transaction lock of its own
so the timer pass and the API pass cannot both send, and a pass spends at most SEND_BUDGET_S on sends: after the first
failed send it stops sending, the rest wait for the next pass.
A reviewed-through baseline (seed_review_baseline) marks the context changes that exist when this ships as reviewed, so
the first review item holds only later agent writes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SubscriptionUsageCursor
from app.services import owner_notice
from app.services.context_changes import DecideRequest, Queue, ReviewItem, build_queue, keep
from app.services.context_changes.queue import target_fold

from .budgets import CellState, cell_states
from .policy import Policy, load_policy
from .why import Why, why

logger = logging.getLogger(__name__)

REVIEW_KEY = "agent-hub-context-review"
BUDGET_KEY_PREFIX = "agent-hub-context-budget:"
STATE_PREFIX = "@context_alert:"
# Nightshift marks an open warning unknown when nothing newer came for 86400 s (items/importer.py STALE_S). Refresh a
# little before, so the item never shows as unknown between two collector passes.
NIGHTSHIFT_STALE = timedelta(hours=24)
REFRESH_AFTER = NIGHTSHIFT_STALE - timedelta(hours=1)
QUEUE_SHOWN = 5
ALERT_LOCK_KEY = 0x55A6E_C0A1  # one sender at a time per key across the timer pass and the API pass (not the collector's)
SEND_BUDGET_S = 60  # most a pass spends on sends; Nightshift's own limit is 30 s a call
DATA_STALE = timedelta(days=8)  # an open budget item with no data to judge it by for this long is closed
BASELINE_STATE = "@context_review_baseline"  # written by the migration at deploy: {"deploy_at": iso, "done": bool}
BASELINE_CHUNK = 100


def budget_key(harness: str, cell: str) -> str:
    return BUDGET_KEY_PREFIX + re.sub(r"[^A-Za-z0-9_.:/@+=,-]", "_", f"{harness}:{cell}")[:150]


def _open_url(path: str) -> str:
    return f"{settings.owner_web_url.rstrip('/')}{path}"


def _k(tokens: int | float | None) -> str:
    return "?" if tokens is None else f"{tokens / 1000:.1f}K"


def _signed_k(tokens: int | None) -> str:
    return "n/a" if tokens is None else f"{tokens / 1000:+.1f}K"


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") else f"{n} {word}s"


def review_notice(queue: Queue) -> dict[str, Any]:
    s = queue.summary
    kinds = [_plural(n, label) for label, n in (("memory", s.by_kind.get("memory", 0)), ("prompt", s.by_kind.get("prompt", 0)),
                                                  ("placement change", s.by_kind.get("placement", 0))) if n]
    body = ", ".join(kinds)
    if s.global_count:
        body += f"; {s.global_count} reach every session"
    if s.tokens_per_day:
        body += f" ({'+' if s.tokens_per_day > 0 else '-'}{abs(s.tokens_per_day)} tokens a day)"
    shown = []
    for row in queue.rows[:QUEUE_SHOWN]:
        who = row.writers[0].session if row.writers and row.writers[0].session else "an agent"
        shown.append(f"- {row.scope_after} {row.target_kind}: {row.title[:80]} (by {who})")
    more = f"\n...and {len(queue.rows) - QUEUE_SHOWN} more" if len(queue.rows) > QUEUE_SHOWN else ""
    return {
        "v": 1, "source": owner_notice.SOURCE, "kind": "todo", "severity": "warning", "push": "tray", "cooldown": 0,
        "title": f"{_plural(s.count, 'context change')} to review", "body": body[:1000],
        "detail": ("Agents changed what Agent Hub delivers. Nothing is blocked; keep, rework or refuse each.\n"
                   + "\n".join(shown) + more)[:4000],
        "key": REVIEW_KEY, "open": _open_url("/context/changes"),
        "fields": [{"label": "Waiting", "value": str(s.count)}, {"label": "Reach every session", "value": str(s.global_count)}],
        "actions": ["open", "done"], "primary": "open",
        "if_ignored": "The changes stay in force; this item refreshes daily while any wait.",
    }


def _knob_names(w: Why) -> str:
    return ", ".join(sorted({k.label for k in w.knobs}))


def _cause_line(w: Why) -> str:
    parts = w.parts
    names = _knob_names(w)
    unknown = "not pinned down"
    if w.cause == "unknown" and w.version.get("from") != w.version.get("to") and names:
        unknown += f" ({w.harness} {w.version.get('from')} -> {w.version.get('to')} and {names} both changed)"
    cause = {
        "config": (f"config changed ({names}), " if names else "the request shape changed with no change of ours, ")
                  + (f"{w.harness} {w.version.get('to')} unchanged" if w.version.get("to") and w.version.get("from") == w.version.get("to")
                     else f"{w.harness} {w.version.get('from')} -> {w.version.get('to')}"),
        "harness_version": f"{w.harness} {w.version.get('from')} -> {w.version.get('to')}",
        "ours": "what Agent Hub delivers",
        "brief": "the starting prompt",
        "model": f"model {w.model.get('from')} -> {w.model.get('to')}",
        "harness": f"the {w.harness} harness itself (no version, config or model change seen)",
        "unknown": unknown,
    }.get(w.cause, "no change found in the data")
    return f"Cause: {cause}. Harness {_signed_k(parts.get('harness'))}, ours {_signed_k(parts.get('ours'))}."


def _knob(w: Why | None) -> str:
    """Only a knob that changed with the move; never the registered list."""
    if w is None:
        return "not checked"
    return _knob_names(w) or "no knob of ours changed"


def _no_rise(w: Why | None, policy: Policy) -> bool:
    """The last day is not above the week before: an over-budget cell that has simply been this size."""
    if w is None or w.delta is None:
        return False
    return w.delta <= 0 or (w.pct is not None and policy.jump_pct is not None and w.pct < policy.jump_pct / 2)


def _size_fields(state: CellState, reason: str) -> list[dict[str, str]]:
    """The two sizes a budget item shows, on the basis its text uses: a jump is judged without the brief (one model), a
    warn level on the plain median of every start."""
    if reason == "jump" and state.body_recent is not None and state.body_baseline is not None:
        return [{"label": "Now, without the brief (24 h median)", "value": _k(state.body_recent)},
                {"label": "Week before, without the brief", "value": _k(state.body_baseline)}]
    return [{"label": "Now (24 h median)", "value": _k(state.recent)}, {"label": "Week before", "value": _k(state.baseline)}]


def budget_notice(state: CellState, w: Why | None, policy: Policy, *, reason: str | None = None, held: bool = False) -> dict[str, Any]:
    """The item for a cell. `reason` overrides state.reason (an item held open between its clear line and its level)."""
    cell = f"{state.harness} {state.cell}"
    reason = reason or state.reason or "warn"
    if reason == "warn" and not held:
        lead = f"{cell} first turn is {_k(state.recent)}, over its {_k(state.warn_tokens)} budget."
    elif reason == "warn":
        lead = f"{cell} first turn is {_k(state.recent)}, still within 10% of its {_k(state.warn_tokens)} budget."
    elif not held:
        lead = (f"{cell} first turn rose {state.body_pct:.0f}% (without the brief) to {_k(state.body_recent)} "
                f"(week before: {_k(state.body_baseline)}).")
    else:
        lead = (f"{cell} first turn (without the brief) is {_k(state.body_recent)}, still {state.body_pct or 0:.0f}% above "
                f"the week before ({_k(state.body_baseline)}).")
    if w is None:
        cause = "Cause: not worked out."
    elif reason == "warn" and _no_rise(w, policy):
        cause = "Cause: no rise in the last day; it has been about this size."
    else:
        cause = _cause_line(w)
    title = (f"{cell} context is over budget" if not held else f"{cell} context is near its budget") if reason == "warn" \
        else f"{cell} context jumped"
    return {
        "v": 1, "source": owner_notice.SOURCE, "kind": "alert", "severity": "warning", "push": "tray", "cooldown": 0,
        "title": title,
        "body": f"{lead} {cause} Knob: {_knob(w)}.",
        "detail": ((w.summary if w is not None else "") +
                   f"\nBudget row: context_budgets {state.harness}/{state.cell} (most specific match). "
                   "It clears itself when the cell is clearly back under.")[:4000],
        "key": budget_key(state.harness, state.cell), "open": _open_url(f"/context/cell/{state.harness}/{state.cell}"),
        "fields": [*_size_fields(state, reason),
                   {"label": "Budget", "value": _k(state.warn_tokens)}, {"label": "Starts in 24 h", "value": str(state.n_recent)}],
        "actions": ["look-into", "open", "mute"], "primary": "look-into",
    }


@dataclass
class Sent:
    open: bool
    sent_at: datetime | None
    reason: str | None = None  # warn | jump: what the budget item was opened for


def _sent_from(state: dict[str, Any] | None) -> Sent:
    state = state or {}
    try:
        sent_at = datetime.fromisoformat(state["sent_at"]) if state.get("sent_at") else None
    except ValueError:
        sent_at = None
    return Sent(open=bool(state.get("open")), sent_at=sent_at, reason=state.get("reason"))


async def _load_states(db: AsyncSession) -> dict[str, Sent]:
    rows = (await db.execute(select(SubscriptionUsageCursor.path, SubscriptionUsageCursor.state)
                             .where(SubscriptionUsageCursor.path.startswith(STATE_PREFIX)))).all()
    return {path.removeprefix(STATE_PREFIX): _sent_from(state) for path, state in rows}


async def _load_state(db: AsyncSession, key: str) -> Sent | None:
    row = (await db.execute(select(SubscriptionUsageCursor.state).where(SubscriptionUsageCursor.path == STATE_PREFIX + key))).first()
    return None if row is None else _sent_from(row[0])


async def _store(db: AsyncSession, key: str, sent: Sent) -> None:
    state = {"open": sent.open, "sent_at": sent.sent_at.isoformat() if sent.sent_at else None, "reason": sent.reason}
    stmt = pg_insert(SubscriptionUsageCursor).values(path=STATE_PREFIX + key, offset=0, state=state)
    await db.execute(stmt.on_conflict_do_update(index_elements=["path"], set_={"state": stmt.excluded.state, "updated_at": func.now()}))


class Sender:
    """One pass's allowance for talking to Nightshift. A slow or failing nightshift costs the pass one call, not one
    per key: after a failed send nothing more is sent this pass, and no send starts past the deadline."""

    def __init__(self, budget_s: float | None = None) -> None:
        self.deadline = time.monotonic() + (SEND_BUDGET_S if budget_s is None else budget_s)
        self.broken = False

    async def run(self, call: Callable[[], Awaitable[bool]]) -> bool | None:
        """The call's result, or None when this pass has no time or trust left for it."""
        remaining = self.deadline - time.monotonic()
        if self.broken or remaining <= 0:
            return None
        try:
            ok = await asyncio.wait_for(call(), timeout=remaining)
        except TimeoutError:
            logger.warning("context alerts: nightshift did not answer in time; no more sends this pass")
            ok = False
        if not ok:
            self.broken = True
        return ok


async def _lock(db: AsyncSession) -> bool:
    return bool((await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ALERT_LOCK_KEY})).scalar())


Want = Callable[[], Awaitable[dict[str, Any]]]


async def sync_item(db: AsyncSession, key: str, want: Want | None, now: datetime, resolved_text: str, sender: Sender, *,
                    reason: str | None = None) -> str:
    """Bring one Nightshift item in line with what is wanted. Returns pushed | refreshed | resolved | quiet | failed |
    deferred (no time left this pass) | busy (another pass is sending).

    `want` builds the notice only when one is due (None: the item should be closed). The state is read again under the
    lock, and committed right after the send, so a later failure in the pass cannot make the next one send it again.
    `reason` is what a budget item is open for, kept for its clear line."""
    if not await _lock(db):
        return "busy"
    previous = await _load_state(db, key)
    was_open = previous is not None and previous.open
    if want is None:
        if not was_open:
            return "quiet"
        sent = await sender.run(lambda: owner_notice.resolve_notice(key, resolved_text))
        if sent is None:
            return "deferred"
        if not sent:
            return "failed"
        await _store(db, key, Sent(open=False, sent_at=previous.sent_at if previous else None, reason=previous.reason if previous else None))
        await db.commit()
        return "resolved"
    due = previous is None or not was_open or previous.sent_at is None or now - previous.sent_at >= REFRESH_AFTER
    if not due:
        return "quiet"
    notice = await want()
    sent = await sender.run(lambda: owner_notice.send_notice(notice))
    if sent is None:
        return "deferred"
    if not sent:
        return "failed"
    await _store(db, key, Sent(open=True, sent_at=now, reason=reason))
    await db.commit()
    return "refreshed" if was_open else "pushed"


def _budget_verdict(state: CellState | None, previous: Sent | None, now: datetime) -> tuple[str, str | None]:
    """(over | hold | clear | wait | idle, the reason it is open for).

    over: the cell is over its level or jumped. hold: it was open and is not yet clearly under (between 90% of the
    level and the level). clear: it was open and is clearly under. wait: it was open and there is too little data to
    say, so it keeps its state; after DATA_STALE of that it is closed."""
    if state is not None and state.reason:
        return "over", state.reason
    if previous is None or not previous.open:
        return "idle", None
    ok = {"warn": state.warn_clear if state else None, "jump": state.jump_clear if state else None}.get(previous.reason or "")
    if previous.reason is None and state is not None:
        ok = state.warn_clear if state.warn_clear is not None else state.jump_clear
    if ok is True:
        return "clear", previous.reason
    if ok is False:
        return "hold", previous.reason
    if previous.sent_at is None or now - previous.sent_at > DATA_STALE:
        return "clear", previous.reason
    return "wait", previous.reason


_CLEARED = {"jump": "Settled: this size is now its usual.", "warn": "Back under its budget."}


async def evaluate(db: AsyncSession, *, now: datetime | None = None, sender: Sender | None = None) -> dict[str, str]:
    """One pass: the review item from the M2 queue, one budget item per cell. Returns what each key did.

    Each key is its own step: it commits after a send and a failure in one is logged and leaves the others alone."""
    now = now or datetime.now(UTC)
    sender = sender or Sender()
    done: dict[str, str] = {}

    async def step(key: str, work: Callable[[], Awaitable[str]]) -> None:
        try:
            done[key] = await work()
        except Exception:
            await db.rollback()
            logger.warning("context alert %s failed", key, exc_info=True)
            done[key] = "error"

    async def baseline() -> str:
        return await seed_review_baseline(db)

    await step("review-baseline", baseline)
    states = await _load_states(db)

    async def review() -> str:
        queue = await build_queue(db)
        want: Want | None = None
        if queue.summary.count:
            async def build() -> dict[str, Any]:
                return review_notice(queue)
            want = build
        return await sync_item(db, REVIEW_KEY, want, now, "Every context change has been reviewed.", sender)

    await step(REVIEW_KEY, review)

    try:
        policy = await load_policy(db)
        cells = {budget_key(s.harness, s.cell): s for s in await cell_states(db, now=now, policy=policy)}
    except Exception:
        await db.rollback()
        logger.warning("context budgets not evaluated", exc_info=True)
        return done
    for key in sorted(cells.keys() | {k for k, p in states.items() if k.startswith(BUDGET_KEY_PREFIX) and p.open}):
        if not key.startswith(BUDGET_KEY_PREFIX):
            continue
        state, previous = cells.get(key), states.get(key)
        verdict, reason = _budget_verdict(state, previous, now)
        if verdict in ("idle", "wait"):
            continue

        async def budget(key: str = key, state: CellState | None = state, verdict: str = verdict, reason: str | None = reason) -> str:
            if verdict == "clear":
                return await sync_item(db, key, None, now, _CLEARED.get(reason or "warn", ""), sender)
            assert state is not None

            async def build() -> dict[str, Any]:
                explained = await why(db, state.harness, state.cell, now=now, policy=policy, recent=True)
                return budget_notice(state, explained, policy, reason=reason, held=verdict == "hold")

            return await sync_item(db, key, build, now, "", sender, reason=reason)

        await step(key, budget)
    return done


async def seed_review_baseline(db: AsyncSession) -> str:
    """Once, after the deploy that adds the review item: context changes written before it count as reviewed.

    The migration leaves a @context_review_baseline row with the deploy time. This marks every queued target reviewed
    through its last revision written by then (M2's own `keep`, as the system), so the first review item holds only
    later agent writes. No row (before the migration) or a done row does nothing; a failure is retried next pass."""
    row = (await db.execute(select(SubscriptionUsageCursor.state).where(SubscriptionUsageCursor.path == BASELINE_STATE))).first()
    if row is None or not row[0] or row[0].get("done"):
        return "quiet"
    deploy_at = datetime.fromisoformat(row[0]["deploy_at"])
    queue = await build_queue(db, automatic=False)
    items: list[ReviewItem] = []
    for queued in queue.rows:
        if queued.first_at > deploy_at:
            continue
        fold = await target_fold(db, queued.target_kind, queued.target_id)
        before = [s for s in fold.steps if s.at <= deploy_at]
        if before:
            items.append(ReviewItem(target_kind=queued.target_kind, target_id=queued.target_id, through_revision=before[-1].id))
    note = "Baseline at deploy: changes written before the review item shipped count as reviewed."
    for i in range(0, len(items), BASELINE_CHUNK):
        await keep(db, DecideRequest(items=items[i:i + BASELINE_CHUNK], note=note))
    stmt = pg_insert(SubscriptionUsageCursor).values(
        path=BASELINE_STATE, offset=0, state={**row[0], "done": True, "marked": len(items), "done_at": datetime.now(UTC).isoformat()})
    await db.execute(stmt.on_conflict_do_update(index_elements=["path"], set_={"state": stmt.excluded.state, "updated_at": func.now()}))
    await db.commit()
    return f"baselined {len(items)}"
