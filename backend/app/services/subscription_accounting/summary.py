"""Accounting summary: cash, credits, subscription headroom and API-equivalent value, kept separate.

- Cash: subscription fees amortized daily (monthly / 30.44, pro-rated by plan period) + metered API spend
  (cost_logs billing_mode='metered') + purchased credit lots. Granted credits are $0 cash.
- Credits: Codex credits drawn per day and project, drawn down by lot (earliest expiry first).
- Utilization: latest 5h / weekly window readings per provider with reset times.
- API-equivalent: tokens x list price. Value received from the flat fees, and the basis for allocating
  those fees across projects and agents. Never spend.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CostLog,
    CreditLot,
    Session,
    SubscriptionPlan,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
)
from app.models.session import NATIVE_COUNTED_NOTE

DAYS_PER_MONTH = 30.44
WEEKLY_ALERT_PERCENT = 80.0
GRANT_LOW_FRACTION = 0.20
EXPIRY_WARN_DAYS = 30
METERED_ANOMALY_RATIO = 2.0
METERED_ANOMALY_MIN_USD = 1.0
API_EQUIV_LABEL = "API-equivalent value at list price. Value received from flat fees, not spend."
WINDOW_LABELS = {300: "5h", 10080: "weekly", 43200: "monthly"}
SOURCE_LABELS = {
    "claude_statusline": "Claude statusline",
    "codex_session_log": "Codex session log",
    "workflow_attempt": "workflow run",
    "opencode_go_usage": "OpenCode usage",
}
# Subscription providers whose Hub-routed value is shown on its own; other providers' value is grouped as "other".
VALUE_PROVIDERS = ("claude", "codex", "opencode-go")
PROVIDER_NAMES = {"opencode-go": "OpenCode Go"}  # alerts title-case any other provider id


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min).astimezone()
    return start, start + timedelta(days=1)


def amortize(plans: list[SubscriptionPlan], day: date) -> list[dict[str, Any]]:
    """Per plan row overlapping `day`: share of the day covered and the amortized $ (None when unpriced)."""
    lo, hi = _day_bounds(day)
    out = []
    for plan in plans:
        start = max(lo, plan.effective_from)
        end = min(hi, plan.effective_to or hi)
        if end <= start:
            continue
        share = (end - start).total_seconds() / 86400
        usd = None if plan.monthly_usd is None else plan.monthly_usd / DAYS_PER_MONTH * share
        out.append({"plan": plan, "share": share, "usd": usd})
    return out


@dataclass
class LotState:
    lot: CreditLot
    remaining: float


def draw_down(lots: list[CreditLot], drawn: float) -> list[LotState]:
    """Allocate total credits drawn to lots, earliest expiry first (no expiry last), then oldest."""
    far = datetime.max.replace(tzinfo=UTC)
    ordered = sorted(lots, key=lambda lot: (lot.expires_at or far, lot.granted_at))
    out = []
    for lot in ordered:
        take = min(lot.credits, max(drawn, 0.0))
        drawn -= take
        out.append(LotState(lot, lot.credits - take))
    return out


async def _plans(db: AsyncSession) -> list[SubscriptionPlan]:
    return list((await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.provider, SubscriptionPlan.effective_from))).scalars())


async def _metered_by_day(db: AsyncSession, start: datetime) -> dict[date, float]:
    """Metered (per-token billed) API spend per local day."""
    rows = await db.execute(
        select(CostLog.created_at, CostLog.cost_usd).where(
            CostLog.created_at >= start, CostLog.billing_mode == "metered", CostLog.cost_usd > 0
        )
    )
    out: dict[date, float] = defaultdict(float)
    for ts, usd in rows.all():
        out[ts.astimezone().date()] += float(usd or 0)
    return out


async def _hub_value(db: AsyncSession, start: datetime) -> tuple[list[dict], list[dict]]:
    """API-equivalent of Hub-routed subscription calls, by project and by agent."""
    base = (
        select(func.sum(CostLog.api_equiv_usd), func.sum(CostLog.credits_used), func.count(CostLog.id))
        .join(Session, CostLog.session_id == Session.id)
        .where(
            CostLog.created_at >= start,
            CostLog.billing_mode == "subscription",
            func.coalesce(CostLog.cost_note, "").not_like(f"{NATIVE_COUNTED_NOTE}%"),  # the collector counts those
        )
    )
    by_project = await db.execute(base.add_columns(Session.project_id, Session.provider).group_by(Session.project_id, Session.provider))
    by_agent = await db.execute(base.add_columns(Session.agent_slug).group_by(Session.agent_slug))
    projects = [
        {"project": p or "unknown", "provider": prov, "api_equiv_usd": float(v or 0), "credits": float(c or 0), "requests": n}
        for v, c, n, p, prov in by_project.all()
    ]
    agents = [
        {"agent": a or "unspecified", "api_equiv_usd": round(float(v or 0), 4), "credits": round(float(c or 0), 2), "requests": n}
        for v, c, n, a in by_agent.all()
    ]
    return projects, sorted(agents, key=lambda r: -r["api_equiv_usd"])


async def _utilization(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(SubscriptionUsageSnapshot).where(SubscriptionUsageSnapshot.observed_at >= now - timedelta(days=8))
        )
    ).scalars().all()
    best: dict[tuple[str, int], SubscriptionUsageSnapshot] = {}
    plan: dict[str, tuple[datetime, str]] = {}
    for r in rows:
        key = (r.provider, r.window_minutes)
        cur = best.get(key)
        # The newest reading of a window wins, whichever source it came from (a headless run updates no statusline).
        if cur is None or (r.observed_at, r.used_percent) > (cur.observed_at, cur.used_percent):
            best[key] = r
        if r.plan_type and (r.provider not in plan or r.observed_at > plan[r.provider][0]):
            plan[r.provider] = (r.observed_at, r.plan_type)
    out: dict[str, dict[str, Any]] = {}
    for (provider, minutes), r in sorted(best.items()):
        reset_passed = r.resets_at is not None and r.resets_at <= now
        entry = out.setdefault(provider, {"provider": provider, "plan_type": plan.get(provider, (None, None))[1], "windows": []})
        entry["windows"].append({
            "window_minutes": minutes,
            "label": WINDOW_LABELS.get(minutes, f"{minutes}m"),
            "used_percent": 0.0 if reset_passed else round(r.used_percent, 1),
            "resets_at": None if reset_passed else (r.resets_at.isoformat() if r.resets_at else None),
            "observed_at": r.observed_at.isoformat(),
            "source": r.source,
            "source_label": SOURCE_LABELS.get(r.source or "", r.source),
            "reset_since_observed": reset_passed,
        })
    return list(out.values())


async def build_summary(db: AsyncSession, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    start_day = today - timedelta(days=days - 1)
    start = _day_bounds(start_day)[0]
    month_start = today.replace(day=1)
    hist_start_day = min(start_day, month_start, today - timedelta(days=21))
    hist_start = _day_bounds(hist_start_day)[0]

    plans = await _plans(db)
    metered = await _metered_by_day(db, hist_start)
    lots = list((await db.execute(select(CreditLot).order_by(CreditLot.granted_at))).scalars())
    daily_rows = list(
        (await db.execute(select(SubscriptionUsageDaily).where(SubscriptionUsageDaily.day >= hist_start_day))).scalars()
    )

    # ---- cash per day
    unverified: set[tuple[str, str]] = set()
    series = []
    for i in range((today - hist_start_day).days + 1):
        d = hist_start_day + timedelta(days=i)
        subs = 0.0
        for part in amortize(plans, d):
            if part["usd"] is None:
                unverified.add((part["plan"].provider, part["plan"].plan))
            else:
                subs += part["usd"]
        lo, hi = _day_bounds(d)
        purchases = sum(lot.paid_usd or 0.0 for lot in lots if lot.source == "purchase" and lo <= lot.granted_at < hi)
        series.append({"date": d.isoformat(), "subscriptions_usd": subs, "metered_usd": metered.get(d, 0.0),
                       "credit_purchases_usd": purchases})
    window = [r for r in series if r["date"] >= start_day.isoformat()]

    def total(rows: list[dict], key: str) -> float:
        return sum(r[key] for r in rows)

    subs_usd, metered_usd, purch_usd = (total(window, k) for k in ("subscriptions_usd", "metered_usd", "credit_purchases_usd"))
    by_provider = defaultdict(lambda: {"amortized_usd": 0.0, "days": 0.0})
    for i in range(days):
        for part in amortize(plans, start_day + timedelta(days=i)):
            row = by_provider[(part["plan"].provider, part["plan"].plan, part["plan"].monthly_usd)]
            row["amortized_usd"] += part["usd"] or 0.0
            row["days"] += part["share"]
    mtd = [r for r in series if r["date"] >= month_start.isoformat()]
    mtd_cash = sum(r["subscriptions_usd"] + r["metered_usd"] + r["credit_purchases_usd"] for r in mtd)
    last7 = series[-7:]
    days_in_month = ((month_start + timedelta(days=32)).replace(day=1) - month_start).days
    remaining_days = days_in_month - today.day
    current_daily_subs = sum(p["usd"] or 0.0 for p in amortize(plans, today)) if remaining_days >= 0 else 0.0
    projected = mtd_cash + remaining_days * (current_daily_subs + total(last7, "metered_usd") / max(len(last7), 1))

    # ---- credits
    drawn_by_day: dict[date, float] = defaultdict(float)
    drawn_by_project: dict[str, float] = defaultdict(float)
    first_lot_day = min((lot.granted_at.astimezone().date() for lot in lots), default=None)
    for r in daily_rows:
        if r.provider == "codex" and r.credits_drawn:
            drawn_by_day[r.day] += r.credits_drawn
            if r.day >= start_day:
                drawn_by_project[r.project] += r.credits_drawn
    drawn_since_lots = sum(v for d, v in drawn_by_day.items() if first_lot_day and d >= first_lot_day)
    if first_lot_day and first_lot_day < hist_start_day:
        drawn_since_lots += await _drawn_between(db, first_lot_day, hist_start_day)
    lot_states = draw_down([lot for lot in lots if lot.provider == "codex"], drawn_since_lots)
    pace_7d = sum(drawn_by_day.get(today - timedelta(days=i), 0.0) for i in range(7)) / 7
    lots_out = []
    for st in lot_states:
        lot = st.lot
        days_left = (lot.expires_at - now).total_seconds() / 86400 if lot.expires_at else None
        unused_at_expiry = max(st.remaining - pace_7d * days_left, 0.0) if days_left is not None else None
        lots_out.append({
            "id": lot.id, "source": lot.source, "credits": lot.credits, "remaining": round(st.remaining, 1),
            "remaining_fraction": round(st.remaining / lot.credits, 3) if lot.credits else None,
            "granted_at": lot.granted_at.isoformat(), "expires_at": lot.expires_at.isoformat() if lot.expires_at else None,
            "days_to_expiry": None if days_left is None else round(days_left, 1),
            "value_usd_per_credit": lot.value_usd_per_credit, "paid_usd": lot.paid_usd,
            "remaining_value_usd": round(st.remaining * lot.value_usd_per_credit, 2) if lot.value_usd_per_credit else None,
            "projected_unused_at_expiry": None if unused_at_expiry is None else round(unused_at_expiry, 0),
            "evidence": lot.evidence,
        })
    balance = sum(s.remaining for s in lot_states)
    credits_window = sum(v for d, v in drawn_by_day.items() if d >= start_day)

    # ---- API-equivalent
    hub_projects, hub_agents = await _hub_value(db, start)
    value_by_provider: dict[str, float] = defaultdict(float)
    tokens_by_provider: dict[str, int] = defaultdict(int)
    unpriced_by_provider: dict[str, int] = defaultdict(int)
    value_by_project: dict[tuple[str, str], float] = defaultdict(float)
    value_by_model: dict[tuple[str, str], float] = defaultdict(float)
    for r in daily_rows:
        if r.day < start_day:
            continue
        value_by_provider[r.provider] += r.api_equiv_usd
        tokens_by_provider[r.provider] += r.input_tokens + r.cached_input_tokens + r.cache_write_tokens + r.output_tokens
        unpriced_by_provider[r.provider] += r.unpriced_tokens
        value_by_project[(r.provider, r.project)] += r.api_equiv_usd
        value_by_model[(r.provider, r.model)] += r.api_equiv_usd
    for row in hub_projects:
        prov = row["provider"] if row["provider"] in VALUE_PROVIDERS else "other"
        value_by_provider[prov] += row["api_equiv_usd"]
        value_by_project[(prov, row["project"])] += row["api_equiv_usd"]
    fee_by_provider: dict[str, float] = defaultdict(float)
    for (prov, _plan, _usd), v in by_provider.items():
        fee_by_provider[prov] += v["amortized_usd"]
    projects: dict[str, dict[str, float]] = defaultdict(lambda: {"api_equiv_usd": 0.0, "allocated_fee_usd": 0.0})
    for (prov, proj), v in value_by_project.items():
        projects[proj]["api_equiv_usd"] += v
        if value_by_provider.get(prov):
            projects[proj]["allocated_fee_usd"] += fee_by_provider.get(prov, 0.0) * v / value_by_provider[prov]
    total_value = sum(value_by_provider.values())

    # ---- alerts
    utilization = await _utilization(db, now)
    alerts = _alerts(utilization, lots_out, drawn_by_day, today, series, unverified, start_day)

    r2 = lambda v: round(v, 2)  # noqa: E731
    return {
        "as_of": now.isoformat(),
        "window": {"start": start_day.isoformat(), "end": today.isoformat(), "days": days},
        "cash": {
            "total_usd": r2(subs_usd + metered_usd + purch_usd),
            "subscriptions_usd": r2(subs_usd),
            "metered_api_usd": r2(metered_usd),
            "credit_purchases_usd": r2(purch_usd),
            "month_to_date_usd": r2(mtd_cash),
            "projected_month_usd": r2(projected),
            "subscriptions": [
                {"provider": p, "plan": n, "monthly_usd": usd, "amortized_usd": r2(v["amortized_usd"]), "days": round(v["days"], 2)}
                for (p, n, usd), v in sorted(by_provider.items(), key=lambda kv: kv[0][:2])
            ],
            "unverified_plans": [{"provider": p, "plan": n} for p, n in sorted(unverified)],
            "daily": [{k: (r2(v) if isinstance(v, float) else v) for k, v in r.items()} for r in window],
        },
        "plans": [
            {"id": p.id, "provider": p.provider, "plan": p.plan, "monthly_usd": p.monthly_usd, "price_verified": p.price_verified,
             "effective_from": p.effective_from.isoformat(), "effective_to": p.effective_to.isoformat() if p.effective_to else None,
             "evidence": p.evidence}
            for p in plans
        ],
        "utilization": utilization,
        "credits": {
            "provider": "codex",
            "used_in_window": round(credits_window, 1),
            "balance": round(balance, 1),
            "burn_per_day_7d": round(pace_7d, 1),
            "cash_usd_in_window": r2(purch_usd),
            "daily": [{"date": d.isoformat(), "credits": round(v, 1)} for d, v in sorted(drawn_by_day.items()) if d >= start_day],
            "by_project": [{"project": p, "credits": round(v, 1)} for p, v in sorted(drawn_by_project.items(), key=lambda kv: -kv[1])],
            "lots": lots_out,
            "attribution_note": "Credits are attributed to the Codex CLI session that reported each balance drop; "
                                "Agent Hub-routed Codex calls draw from the same balance.",
        },
        "api_equivalent": {
            "label": API_EQUIV_LABEL,
            "total_usd": r2(total_value),
            "by_provider": [
                {"provider": p, "api_equiv_usd": r2(v), "tokens": tokens_by_provider.get(p, 0),
                 "unpriced_tokens": unpriced_by_provider.get(p, 0), "fee_usd": r2(fee_by_provider.get(p, 0.0)),
                 "leverage": round(v / fee_by_provider[p], 1) if fee_by_provider.get(p) else None}
                for p, v in sorted(value_by_provider.items(), key=lambda kv: -kv[1])
            ],
            "by_model": [
                {"provider": p, "model": m, "api_equiv_usd": r2(v)}
                for (p, m), v in sorted(value_by_model.items(), key=lambda kv: -kv[1]) if v > 0.005
            ],
            "by_project": [
                {"project": p, "api_equiv_usd": r2(v["api_equiv_usd"]),
                 "share": round(v["api_equiv_usd"] / total_value, 4) if total_value else None,
                 "allocated_fee_usd": r2(v["allocated_fee_usd"])}
                for p, v in sorted(projects.items(), key=lambda kv: -kv[1]["api_equiv_usd"]) if v["api_equiv_usd"] > 0.005
            ],
            "by_agent": hub_agents,
        },
        "alerts": alerts,
    }


async def _drawn_between(db: AsyncSession, lo: date, hi: date) -> float:
    value = await db.scalar(
        select(func.sum(SubscriptionUsageDaily.credits_drawn)).where(
            SubscriptionUsageDaily.provider == "codex", SubscriptionUsageDaily.day >= lo, SubscriptionUsageDaily.day < hi
        )
    )
    return float(value or 0.0)


def _alerts(
    utilization: list[dict], lots: list[dict], drawn_by_day: dict[date, float], today: date,
    series: list[dict], unverified: set[tuple[str, str]], start_day: date,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for prov in utilization:
        for w in prov["windows"]:
            if w["window_minutes"] == 10080 and w["used_percent"] >= WEEKLY_ALERT_PERCENT:
                name = PROVIDER_NAMES.get(prov["provider"], prov["provider"].title())
                alerts.append({"code": f"{prov['provider']}.weekly_high", "severity": "warning",
                               "message": f"{name} weekly limit {w['used_percent']:.0f}% used",
                               "resets_at": w["resets_at"]})
    drawn_today = drawn_by_day.get(today, 0.0)
    if drawn_today > 0:
        alerts.append({"code": "codex.credits_drawing", "severity": "info",
                       "message": f"Codex is drawing credits: {drawn_today:,.0f} today"})
    for lot in lots:
        if lot["source"] == "grant" and lot["remaining_fraction"] is not None:
            if 0 < lot["remaining_fraction"] < GRANT_LOW_FRACTION:
                alerts.append({"code": "codex.grant_low", "severity": "warning",
                               "message": f"Codex credit grant {lot['remaining_fraction']:.0%} left ({lot['remaining']:,.0f})"})
            unused = lot["projected_unused_at_expiry"] or 0
            if (lot["days_to_expiry"] is not None and 0 < lot["days_to_expiry"] <= EXPIRY_WARN_DAYS
                    and unused >= GRANT_LOW_FRACTION * lot["credits"]):
                alerts.append({"code": "codex.grant_expiring", "severity": "warning",
                               "message": f"Codex grant expires in {lot['days_to_expiry']:.0f} days; "
                                          f"about {unused:,.0f} credits would go unused at the current pace"})
        if lot["source"] == "purchase" and lot["remaining"] < lot["credits"] and drawn_today > 0:
            alerts.append({"code": "codex.purchased_credits_in_use", "severity": "critical",
                           "message": "Codex is drawing purchased credits (real cash)"})
        if lot["source"] == "unclassified":
            alerts.append({"code": "codex.lot_unclassified", "severity": "warning", "lot_id": lot["id"],
                           "message": f"New Codex credits detected ({lot['credits']:,.0f}): granted or purchased?"})
    prior = [r["metered_usd"] for r in series[-15:-1]]
    if prior and series:
        med = statistics.median(prior)
        last = series[-1]["metered_usd"]
        if last >= METERED_ANOMALY_MIN_USD and last > METERED_ANOMALY_RATIO * med:
            alerts.append({"code": "metered.anomaly", "severity": "warning",
                           "message": f"Metered API spend ${last:.2f} today vs ${med:.2f} typical"})
    if unverified:
        alerts.append({"code": "plans.unverified", "severity": "info",
                       "message": "Plan price unverified: " + ", ".join(f"{p} {n}" for p, n in sorted(unverified)),
                       "since": start_day.isoformat()})
    return alerts
