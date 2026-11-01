"""Nightshift items for context: one rolling review item and one budget item per cell over its level.

Both go to the tray and the board, never the phone (push "tray"). Each is one live item per key:
  - agent-hub-context-review: pushed when the review queue goes from empty to N, refreshed once per Nightshift
    STALE_S while it stays non-empty (an open warning nothing newer touched for that long shows as unknown), resolved
    at 0. A refresh is a new log entry, so it shows as a desktop card again: that is why it is not sent on every change.
  - agent-hub-context-budget:<harness>:<cell>: sent when the cell goes over, refreshed the same way, resolved when
    it is back under. The text names the cause (`why`) and the knob.
What was sent, and when, is kept in subscription_usage_cursors rows named @context_alert:<key>.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SubscriptionUsageCursor
from app.services import owner_notice
from app.services.context_changes import Queue, build_queue

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


def _cause_line(w: Why) -> str:
    parts = w.parts
    cause = {
        "config": f"config changed ({', '.join(sorted({k.label for k in w.knobs})) or 'fingerprint'}), "
                  f"{w.harness} {w.version.get('to') or ''} unchanged",
        "harness_version": f"{w.harness} {w.version.get('from')} -> {w.version.get('to')}",
        "ours": "what Agent Hub delivers",
        "brief": "the starting prompt",
        "model": f"model {w.model.get('from')} -> {w.model.get('to')}",
    }.get(w.cause, "no change found in the data")
    return f"Cause: {cause}. Harness {_signed_k(parts.get('harness'))}, ours {_signed_k(parts.get('ours'))}."


def _knob(w: Why | None, policy: Policy, state: CellState) -> str:
    if w is not None and w.knobs:
        return ", ".join(sorted({k.label for k in w.knobs}))
    names = [k.name for k in policy.knobs_for(state.harness, state.cell)]
    return ", ".join(names) or "none registered"


def budget_notice(state: CellState, w: Why | None, policy: Policy) -> dict[str, Any]:
    cell = f"{state.harness} {state.cell}"
    if state.reason == "warn":
        lead = f"{cell} first turn is {_k(state.recent)}, over its {_k(state.warn_tokens)} budget."
    else:
        lead = f"{cell} first turn rose {state.pct:.0f}% to {_k(state.recent)} (week before: {_k(state.baseline)})."
    knob = _knob(w, policy, state)
    cause = _cause_line(w) if w is not None else "Cause: not worked out."
    return {
        "v": 1, "source": owner_notice.SOURCE, "kind": "alert", "severity": "warning", "push": "tray", "cooldown": 0,
        "title": f"{cell} context is over budget" if state.reason == "warn" else f"{cell} context jumped",
        "body": f"{lead} {cause} Knob: {knob}.",
        "detail": ((w.summary if w is not None else "") +
                   f"\nBudget row: context_budgets {state.harness}/{state.cell} (most specific match). "
                   "It clears itself when the cell is back under.")[:4000],
        "key": budget_key(state.harness, state.cell), "open": _open_url(f"/context/cell/{state.harness}/{state.cell}"),
        "fields": [{"label": "Now (24 h median)", "value": _k(state.recent)}, {"label": "Week before", "value": _k(state.baseline)},
                   {"label": "Budget", "value": _k(state.warn_tokens)}, {"label": "Starts in 24 h", "value": str(state.n_recent)}],
        "actions": ["look-into", "open", "mute"], "primary": "look-into",
    }


@dataclass
class Sent:
    open: bool
    sent_at: datetime | None


async def _load_states(db: AsyncSession) -> dict[str, Sent]:
    rows = (await db.execute(select(SubscriptionUsageCursor).where(SubscriptionUsageCursor.path.startswith(STATE_PREFIX)))).scalars().all()
    out = {}
    for row in rows:
        state = row.state or {}
        try:
            sent_at = datetime.fromisoformat(state["sent_at"]) if state.get("sent_at") else None
        except ValueError:
            sent_at = None
        out[row.path.removeprefix(STATE_PREFIX)] = Sent(open=bool(state.get("open")), sent_at=sent_at)
    return out


async def _store(db: AsyncSession, key: str, sent: Sent) -> None:
    state = {"open": sent.open, "sent_at": sent.sent_at.isoformat() if sent.sent_at else None}
    stmt = pg_insert(SubscriptionUsageCursor).values(path=STATE_PREFIX + key, offset=0, state=state)
    await db.execute(stmt.on_conflict_do_update(index_elements=["path"], set_={"state": stmt.excluded.state, "updated_at": func.now()}))


async def sync_item(db: AsyncSession, key: str, notice: dict[str, Any] | None, previous: Sent | None, now: datetime,
                    resolved_text: str) -> str:
    """Bring one Nightshift item in line with what is wanted. Returns pushed | refreshed | resolved | quiet | failed."""
    was_open = previous is not None and previous.open
    if notice is None:
        if not was_open:
            return "quiet"
        if not await owner_notice.resolve_notice(key, resolved_text):
            return "failed"
        await _store(db, key, Sent(open=False, sent_at=previous.sent_at if previous else None))
        return "resolved"
    due = previous is None or not was_open or previous.sent_at is None or now - previous.sent_at >= REFRESH_AFTER
    if not due:
        return "quiet"
    if not await owner_notice.send_notice(notice):
        return "failed"
    await _store(db, key, Sent(open=True, sent_at=now))
    return "refreshed" if was_open else "pushed"


async def evaluate(db: AsyncSession, *, now: datetime | None = None) -> dict[str, str]:
    """One pass: the review item from the M2 queue, one budget item per cell. Returns what each key did."""
    now = now or datetime.now(UTC)
    states = await _load_states(db)
    done: dict[str, str] = {}

    queue = await build_queue(db)
    review = review_notice(queue) if queue.summary.count else None
    done[REVIEW_KEY] = await sync_item(db, REVIEW_KEY, review, states.get(REVIEW_KEY), now, "Every context change has been reviewed.")

    policy = await load_policy(db)
    over = {budget_key(s.harness, s.cell): s for s in await cell_states(db, now=now, policy=policy) if s.reason}
    for key, state in over.items():
        previous = states.get(key)
        if previous is not None and previous.open and previous.sent_at is not None and now - previous.sent_at < REFRESH_AFTER:
            done[key] = "quiet"  # nothing to send yet: skip working out the cause
            continue
        explained = await why(db, state.harness, state.cell, now=now, policy=policy)
        done[key] = await sync_item(db, key, budget_notice(state, explained, policy), previous, now, "")
    for key, previous in states.items():
        if key.startswith(BUDGET_KEY_PREFIX) and key not in over and previous.open:
            done[key] = await sync_item(db, key, None, previous, now, "Back under its budget.")
    return done
