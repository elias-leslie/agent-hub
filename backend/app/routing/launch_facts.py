"""Usage facts for launch options: what each tool still has, until when, and its last refusal.

Facts only. Nothing here ranks, orders or blocks an option; ``allowed`` comes from the deny rows alone.
The thresholds a coordinator weighs (is 9% left enough?) are the coordinator's call, so none live here.

Rules, all derived from the readings themselves:
- A window reading is unknown only once its reset has passed; until then it is shown with its age.
- A window whose reset passed while its provider has since reported another window is "not reported"
  (Claude now reports only the 7-day window); it does not make the option unknown.
- A window at 100% is used up until it resets; a provider with a credit balance runs on credits then.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog import resolve_model
from app.llm.utils.outcomes import is_model_switch
from app.models import (
    CreditLot,
    Session,
    SessionEvent,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
)
from app.services.subscription_accounting.summary import (
    WINDOW_LABELS,
    draw_down,
    latest_readings,
    pace_per_day,
)

REFUSAL_ROWS = 1000  # newest refusals read; far above what a handful of models ever collect


@dataclass
class Facts:
    readings: list[SubscriptionUsageSnapshot] = field(default_factory=list)
    credits: dict[str, dict[str, Any]] = field(default_factory=dict)
    refusals: list[dict[str, Any]] = field(default_factory=list)


def _seconds(delta: Any) -> int:
    return max(int(delta.total_seconds()), 0)


def window_facts(readings: list[SubscriptionUsageSnapshot], now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Per provider, one entry per window in its latest readings, shortest window first."""
    by_provider: dict[str, list[SubscriptionUsageSnapshot]] = defaultdict(list)
    for r in readings:
        by_provider[r.provider].append(r)
    out: dict[str, list[dict[str, Any]]] = {}
    for provider, rows in by_provider.items():
        current = [r for r in rows if not _reset_passed(r, now)]
        windows = []
        for r in sorted(rows, key=lambda r: r.window_minutes):
            base = {"window_minutes": r.window_minutes, "label": WINDOW_LABELS.get(r.window_minutes, f"{r.window_minutes}m"),
                    "observed_at": r.observed_at.isoformat(), "age_seconds": _seconds(now - r.observed_at),
                    "source": r.source, "used_percent": None, "left_percent": None, "resets_at": None,
                    "resets_in_seconds": None}
            if _reset_passed(r, now):
                # Not reported: the provider has read another window since this one reset.
                superseded = any(c.observed_at > r.observed_at for c in current)
                windows.append(base | {"state": "not_reported" if superseded else "unknown"})
                continue
            used = round(r.used_percent, 1)
            windows.append(base | {
                "state": "used_up" if used >= 100 else "ok", "used_percent": used,
                "left_percent": round(max(100 - used, 0), 1),
                "resets_at": r.resets_at.isoformat() if r.resets_at else None,
                "resets_in_seconds": _seconds(r.resets_at - now) if r.resets_at else None,
            })
        out[provider] = windows
    return out


def _reset_passed(r: SubscriptionUsageSnapshot, now: datetime) -> bool:
    return r.resets_at is not None and r.resets_at <= now


def credit_facts(lots: list[CreditLot], drawn_since_lots: float, drawn_by_day: dict, today: Any) -> dict[str, Any]:
    """Balance, the last-7-day pace and the earliest expiry of a lot that still has credits."""
    states = draw_down(lots, drawn_since_lots)
    balance = sum(s.remaining for s in states)
    expiries = [s.lot.expires_at for s in states if s.remaining > 0 and s.lot.expires_at]
    return {"balance": round(balance, 1), "pace_per_day_7d": round(pace_per_day(drawn_by_day, today), 1),
            "earliest_expiry": min(expiries).isoformat() if expiries else None}


def option_usage(provider: str | None, windows: dict[str, list[dict]], credits: dict[str, dict], now: datetime) -> dict:
    """The usage block of one option. ``status``: ok, used_up, on_credits, unknown, or untracked (no
    usage source for this tool)."""
    if provider is None:
        return {"provider": None, "status": "untracked", "windows": [], "credits": None}
    own = windows.get(provider, [])
    credit = credits.get(provider)
    used_up = [w for w in own if w["state"] == "used_up"]
    if used_up:
        status = "on_credits" if credit and credit["balance"] > 0 else "used_up"
    elif any(w["state"] == "ok" for w in own):
        status = "ok"
    else:
        status = "unknown"
    out_credit = None
    if credit is not None:
        # Until the window that is used up resets, else the week: do the credits last that long?
        ref = max(used_up, key=lambda w: w["resets_in_seconds"] or 0) if used_up else next(
            (w for w in own if w["window_minutes"] == 10080 and w["state"] == "ok"), None)
        reset_in = ref["resets_in_seconds"] if ref else None
        pace = credit["pace_per_day_7d"]
        days = credit["balance"] / pace if pace > 0 else None
        out_credit = credit | {
            "lasts_days": None if days is None else round(days, 1),
            "reset_at": ref["resets_at"] if ref else None,
            "lasts_past_reset": None if reset_in is None else (days is None or days * 86400 > reset_in),
        }
    return {"provider": provider, "status": status, "windows": own, "credits": out_credit}


def usage_provider(launch: dict, tool: str, model: str | None) -> str | None:
    """The subscription whose usage a tool/model draws on: the provider a model id names ("opencode-go/..."
    when ``launch.usage_providers`` lists it), else the tool's ``usage_provider``, else none."""
    prefix = model.split("/", 1)[0] if model and "/" in model else None
    if prefix in launch.get("usage_providers", []):
        return prefix
    return launch["tools"][tool].get("usage_provider")


def last_refusal(model: str | None, refusals: list[dict]) -> dict | None:
    """The newest refusal whose requested model is this model, and how many are recorded. Never changes
    ``allowed``: a refusal sends that request to the next option, nothing more."""
    if not model:
        return None
    mine = [r for r in refusals if not is_model_switch(r["requested_model"], resolve_model(model))
            or not is_model_switch(r["requested_model"], model)]
    return None if not mine else {**mine[0], "count": len(mine)}


def attach(payload: dict, facts: Facts, launch: dict, now: datetime) -> dict:
    """Add ``usage`` and ``last_refusal`` to every row (and ``last_refusal`` to its alternates). A denied
    row keeps its usage but gets no refusal line: the rule already says no."""
    windows = window_facts(facts.readings, now)
    for row in payload["rows"]:
        row["usage"] = option_usage(usage_provider(launch, row["tool"], row.get("model")), windows, facts.credits, now)
        row["last_refusal"] = None if not row["allowed"] else last_refusal(row.get("model"), facts.refusals)
        for alt in row.get("alternates", []):
            alt["last_refusal"] = None if not row["allowed"] else last_refusal(alt.get("model"), facts.refusals)
    payload["facts_as_of"] = now.isoformat()
    return payload


async def load_facts(db: AsyncSession, now: datetime | None = None) -> Facts:
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    lots_by_provider: dict[str, list[CreditLot]] = defaultdict(list)
    for lot in (await db.execute(select(CreditLot))).scalars():
        lots_by_provider[lot.provider].append(lot)
    credits = {}
    for provider, lots in lots_by_provider.items():
        first_day = min(lot.granted_at.astimezone().date() for lot in lots)
        rows = (await db.execute(select(SubscriptionUsageDaily.day, SubscriptionUsageDaily.credits_drawn).where(
            SubscriptionUsageDaily.provider == provider, SubscriptionUsageDaily.day >= first_day,
            SubscriptionUsageDaily.credits_drawn > 0))).all()
        by_day: dict = defaultdict(float)
        for day, drawn in rows:
            by_day[day] += drawn
        credits[provider] = credit_facts(lots, sum(by_day.values()), by_day, today)
    return Facts(readings=await latest_readings(db, now), credits=credits, refusals=await _refusals(db))


async def _refusals(db: AsyncSession) -> list[dict[str, Any]]:
    """Newest first. Keyed on the refusal's own requested_model: some events have no model_used."""
    kind = SessionEvent.usage["provider_outcome"]["kind"].as_string()
    rows = (await db.execute(
        select(SessionEvent.created_at, SessionEvent.usage, Session.provider_metadata, Session.project_id)
        .join(Session, Session.id == SessionEvent.session_id, isouter=True)
        .where(kind == "refused").order_by(SessionEvent.created_at.desc()).limit(REFUSAL_ROWS)
    )).all()
    out = []
    for created_at, usage, metadata, project in rows:
        outcome = (usage or {}).get("provider_outcome") or {}
        role = ((metadata or {}).get("work_role") or {}).get("id") if isinstance(metadata, dict) else None
        if outcome.get("requested_model"):
            out.append({"requested_model": outcome["requested_model"], "at": created_at.isoformat(),
                        "role": role, "project": project, "category": outcome.get("category")})
    return out
