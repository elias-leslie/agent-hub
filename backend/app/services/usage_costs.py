"""Agent spend in one place: transcript calls (usage_calls, Claude Code and Codex with sub-agents) and
Agent Hub completions (cost_logs), priced at API list price (subscription usage counts at its
API-equivalent value). Feeds the Costs page and the runaway alert.

Rows are sessions the owner started (interactive) or routine jobs (scheduled / scripted runs that share
a job name); sub-agents roll up into their root session.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RANGES: dict[str, tuple[timedelta, timedelta]] = {
    "1h": (timedelta(hours=1), timedelta(minutes=5)),
    "24h": (timedelta(hours=24), timedelta(hours=1)),
    "7d": (timedelta(days=7), timedelta(hours=6)),
    "30d": (timedelta(days=30), timedelta(days=1)),
}
KINDS = ("interactive", "routine", "other")
ITEM_LIMIT = 50
RATE_WINDOW = timedelta(minutes=15)
HISTORY_DAYS = 28

# One row per call. cost_logs completions from Nightshift are routine; other app completions are "other".
# Transcript sessions already replayed by Agent Hub's own providers never write transcripts, so nothing
# is counted twice.
_SPEND_CTE = """
spend AS (
    SELECT c.occurred_at AS ts,
           coalesce(c.api_equiv_usd, 0) AS usd,
           c.input_tokens + c.cached_input_tokens + c.cache_write_tokens + c.output_tokens AS tokens,
           c.provider, c.model, c.session_id, c.agent_id,
           CASE WHEN c.agent_id = '' THEN NULL ELSE coalesce(a.title, 'sub-agent') END AS agent_name,
           coalesce(r.kind, a.kind, 'other') AS kind,
           coalesce(hs.project_id, nullif(r.project, 'unknown'), a.project, 'unknown') AS project,
           CASE WHEN r.kind = 'routine' AND r.job IS NOT NULL THEN 'job:' || r.job
                ELSE 'session:' || c.provider || ':' || c.session_id END AS item,
           CASE WHEN r.kind = 'routine' AND r.job IS NOT NULL THEN r.job
                ELSE coalesce(hs.summary_oneliner, r.title, a.title, left(c.session_id, 8)) END AS name,
           c.api_equiv_usd IS NULL AS unpriced
    FROM usage_calls c
    LEFT JOIN usage_sessions r
           ON r.provider = c.provider AND r.session_id = c.session_id AND r.agent_id = ''
    LEFT JOIN usage_sessions a
           ON c.agent_id <> '' AND a.provider = c.provider AND a.session_id = c.session_id
          AND a.agent_id = c.agent_id
    LEFT JOIN sessions hs ON hs.id = c.session_id
    WHERE c.occurred_at >= :start AND c.occurred_at < :end
    UNION ALL
    SELECT l.created_at,
           greatest(coalesce(l.cost_usd, 0), coalesce(l.api_equiv_usd, 0)),
           coalesce(l.input_tokens, 0) + coalesce(l.output_tokens, 0) + coalesce(l.cache_read_tokens, 0)
               + coalesce(l.cache_write_tokens, 0),
           coalesce(s.provider, 'api'), l.model, coalesce(l.session_id, ''), '', NULL,
           CASE WHEN left(s.request_source, 10) = 'nightshift' THEN 'routine' ELSE 'other' END,
           coalesce(s.project_id, 'unknown'),
           'job:' || coalesce(s.request_source, 'api') || coalesce(' · ' || s.agent_slug, ''),
           coalesce(s.request_source, 'api') || coalesce(' · ' || s.agent_slug, ''),
           l.cost_usd IS NULL AND l.api_equiv_usd IS NULL
    FROM cost_logs l
    LEFT JOIN sessions s ON s.id = l.session_id
    WHERE l.created_at >= :start AND l.created_at < :end
)
"""

_RANGE_SQL = text(
    f"""
    WITH {_SPEND_CTE}
    SELECT date_bin(:bucket, ts, :origin) AS b, item, max(name) AS name, kind, project, model,
           sum(usd) AS usd, sum(tokens) AS tokens, count(*) AS calls, count(*) FILTER (WHERE unpriced) AS unpriced
    FROM spend
    GROUP BY 1, item, kind, project, model
    """
)

_SERIES_SQL = text(
    f"""
    WITH {_SPEND_CTE}
    SELECT date_bin(:bucket, ts, :origin) AS b, sum(usd) FROM spend GROUP BY 1
    """
)

_ITEM_CALLS_SQL = text(
    f"""
    WITH {_SPEND_CTE}
    SELECT ts, usd, tokens, model, session_id, agent_id, agent_name, name, kind, project
    FROM spend WHERE item = :item
    """
)

# Baselines start where the call ledger starts: completion logs reach further back but
# carry a sliver of the spend, so counting them would make earlier weeks look idle.
_FIRST_DATA_SQL = text(
    "SELECT coalesce((SELECT min(occurred_at) FROM usage_calls), (SELECT min(created_at) FROM cost_logs))"
)

# Agent work Agent Hub knows about in the window, and whether any usage came with it.
_COVERAGE_SQL = text(
    """
    SELECT s.session_type::text, s.provider, count(*) AS total,
           count(*) FILTER (WHERE
               EXISTS (SELECT 1 FROM usage_calls c WHERE c.session_id = s.id)
               OR EXISTS (SELECT 1 FROM usage_calls c WHERE c.agent_id = s.id AND c.agent_id <> '')
               OR EXISTS (SELECT 1 FROM cost_logs l WHERE l.session_id = s.id)
               OR EXISTS (SELECT 1 FROM session_events e WHERE e.session_id = s.id AND e.event_type = 'usage')
           ) AS captured
    FROM sessions s
    WHERE s.session_type::text IN ('claude_code', 'agent', 'completion')
      AND coalesce(s.last_activity_at, s.updated_at) >= :start AND s.created_at < :end
      AND (s.session_type::text <> 'claude_code' OR EXISTS (
          SELECT 1 FROM session_events e WHERE e.session_id = s.id AND e.event_type IN ('message', 'tool_use')))
    GROUP BY 1, 2
    """
)

SOURCE_LABELS = {"claude_code": "Claude Code", "agent": "Codex", "completion": "completions"}


@dataclass(frozen=True)
class Window:
    range: str
    start: datetime
    end: datetime
    bucket: timedelta
    origin: datetime


def local_midnight(now: datetime) -> datetime:
    local = now.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def window_for(range_key: str, now: datetime | None = None) -> Window:
    span, bucket = RANGES.get(range_key, RANGES["24h"])
    now = now or datetime.now(UTC)
    origin = local_midnight(now)
    steps = math.ceil((now - origin) / bucket)
    end = origin + steps * bucket
    if end <= now:
        end += bucket
    return Window(range_key if range_key in RANGES else "24h", end - span, end, bucket, origin)


def _params(start: datetime, end: datetime, **extra: Any) -> dict[str, Any]:
    return {"start": start, "end": end, **extra}


def _ratio(value: float, typical: float | None) -> float | None:
    if typical is None or typical <= 0.01:
        return None
    return round(value / typical, 2)


async def _summary(db: AsyncSession, now: datetime) -> dict[str, Any]:
    first = (await db.execute(_FIRST_DATA_SQL)).scalar()
    hist_start = now - timedelta(days=HISTORY_DAYS)
    if first is not None:
        hist_start = max(hist_start, first)
    rows = (
        await db.execute(
            _SERIES_SQL,
            _params(hist_start, now, bucket=timedelta(minutes=15), origin=local_midnight(now)),
        )
    ).all()
    series = [(b, float(usd or 0)) for b, usd in rows]

    def spent(start: datetime, end: datetime) -> float:
        return sum(usd for b, usd in series if start <= b < end)

    covered = (now - hist_start).total_seconds() / 86400
    rate = spent(now - RATE_WINDOW, now) * (timedelta(hours=1) / RATE_WINDOW)
    week_hours = min(covered, 7) * 24
    typical_rate = spent(now - timedelta(days=7), now) / week_hours if week_hours >= 6 else None

    midnight = local_midnight(now)
    elapsed = now - midnight
    today = spent(midnight, now)
    prior_days = [
        spent(midnight - timedelta(days=k), midnight - timedelta(days=k) + elapsed)
        for k in range(1, 8)
        if midnight - timedelta(days=k) >= hist_start
    ]
    typical_today = sum(prior_days) / len(prior_days) if prior_days else None

    week = spent(now - timedelta(days=7), now)
    prior_weeks = [
        spent(now - timedelta(days=7 * (k + 1)), now - timedelta(days=7 * k))
        for k in range(1, 4)
        if now - timedelta(days=7 * (k + 1)) >= hist_start
    ]
    typical_week = sum(prior_weeks) / len(prior_weeks) if prior_weeks else None
    return {
        "rate_per_hour": round(rate, 2),
        "rate_typical": None if typical_rate is None else round(typical_rate, 2),
        "rate_ratio": _ratio(rate, typical_rate),
        "today": round(today, 2),
        "today_typical": None if typical_today is None else round(typical_today, 2),
        "today_ratio": _ratio(today, typical_today),
        "week": round(week, 2),
        "week_typical": None if typical_week is None else round(typical_week, 2),
        "week_ratio": _ratio(week, typical_week),
        "data_since": first.isoformat() if first else None,
    }


async def coverage(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    rows = (await db.execute(_COVERAGE_SQL, _params(start, end))).all()
    total = sum(int(r.total) for r in rows)
    captured = sum(int(r.captured) for r in rows)
    gaps: dict[str, int] = defaultdict(int)
    for r in rows:
        missing = int(r.total) - int(r.captured)
        if missing:
            label = SOURCE_LABELS.get(r.session_type, r.session_type)
            if r.session_type == "completion":
                label = f"{r.provider} completions"
            gaps[label] += missing
    return {
        "percent": None if total == 0 else round(100 * captured / total, 1),
        "sessions": total,
        "captured": captured,
        "uncaptured": [{"source": k, "sessions": v} for k, v in sorted(gaps.items(), key=lambda kv: -kv[1])],
    }


def _matches(row: Any, project: str | None, model: str | None, kind: str | None) -> bool:
    return (
        (project is None or row.project == project)
        and (model is None or row.model == model)
        and (kind is None or row.kind == kind)
    )


async def overview(
    db: AsyncSession,
    range_key: str = "24h",
    *,
    bucket_at: datetime | None = None,
    project: str | None = None,
    model: str | None = None,
    kind: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    win = window_for(range_key, now)
    rows = (
        await db.execute(
            _RANGE_SQL, _params(win.start, win.end, bucket=win.bucket, origin=win.origin)
        )
    ).all()
    starts = [win.start + i * win.bucket for i in range(int((win.end - win.start) / win.bucket))]
    index = {b: i for i, b in enumerate(starts)}
    options: dict[str, dict[str, float]] = {"project": defaultdict(float), "model": defaultdict(float), "kind": defaultdict(float)}
    chart: list[dict[str, Any]] = [{"start": b.isoformat(), **dict.fromkeys(KINDS, 0.0)} for b in starts]
    items: dict[str, dict[str, Any]] = {}
    unpriced = 0
    for r in rows:
        usd = float(r.usd or 0)
        for name in ("project", "model", "kind"):
            options[name][getattr(r, name)] += usd
        if not _matches(r, project, model, kind):
            continue
        i = index.get(r.b)
        if i is None:
            continue
        chart[i][r.kind if r.kind in KINDS else "other"] += usd
        if bucket_at is not None and r.b != bucket_at:
            continue
        item: dict[str, Any] | None = items.get(r.item)
        if item is None:
            item = {
                "key": r.item, "name": r.name, "kind": r.kind, "usd": 0.0, "tokens": 0, "calls": 0,
                "projects": defaultdict(float), "spark": [0.0] * len(starts),
            }
            items[r.item] = item
        item["usd"] += usd
        item["tokens"] += int(r.tokens or 0)
        item["calls"] += int(r.calls or 0)
        item["projects"][r.project] += usd
        item["spark"][i] += usd
        unpriced += int(r.unpriced or 0)
    total = sum(it["usd"] for it in items.values())
    ranked = sorted(items.values(), key=lambda it: -it["usd"])[:ITEM_LIMIT]
    for it in ranked:
        projects = it.pop("projects")
        it["project"] = max(projects, key=lambda p: projects[p]) if projects else "unknown"
        it["share"] = round(it["usd"] / total, 4) if total > 0 else 0.0
        it["usd"] = round(it["usd"], 4)
        it["spark"] = [round(v, 4) for v in it["spark"]]
    for bar in chart:
        for k in KINDS:
            bar[k] = round(bar[k], 4)
    return {
        "range": win.range,
        "start": win.start.isoformat(),
        "end": win.end.isoformat(),
        "bucket_seconds": int(win.bucket.total_seconds()),
        "selected_bucket": bucket_at.isoformat() if bucket_at else None,
        "summary": await _summary(db, now),
        "chart": chart,
        "total_usd": round(total, 4),
        "unpriced_calls": unpriced,
        "item_count": len(items),
        "items": ranked,
        "filters": {
            name: [k for k, _ in sorted(values.items(), key=lambda kv: -kv[1])]
            for name, values in options.items()
        },
        "coverage": await coverage(db, win.start, win.end),
    }


async def item_detail(db: AsyncSession, item: str, range_key: str = "7d", now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    win = window_for(range_key, now)
    rows = (await db.execute(_ITEM_CALLS_SQL, _params(win.start, win.end, item=item))).all()
    starts = [win.start + i * win.bucket for i in range(int((win.end - win.start) / win.bucket))]
    timeline = [0.0] * len(starts)
    agents: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    runs: dict[str, float] = defaultdict(float)
    for r in rows:
        usd = float(r.usd or 0)
        i = int((r.ts - win.start) / win.bucket)
        if 0 <= i < len(timeline):
            timeline[i] += usd
        akey = r.agent_id or ""
        agent = agents.setdefault(akey, {"name": r.agent_name or "main session", "usd": 0.0, "tokens": 0, "calls": 0})
        agent["usd"] += usd
        agent["tokens"] += int(r.tokens or 0)
        agent["calls"] += 1
        model = models.setdefault(r.model, {"model": r.model, "usd": 0.0, "tokens": 0, "calls": 0})
        model["usd"] += usd
        model["tokens"] += int(r.tokens or 0)
        model["calls"] += 1
        runs[r.session_id] += usd
    total = sum(timeline)
    top = sorted(rows, key=lambda r: -float(r.usd or 0))[:10]
    first = rows[0] if rows else None
    is_job = item.startswith("job:")
    days = max((win.end - win.start) / timedelta(days=1), 1 / 24)
    sub_agents = sorted(
        ({"key": k, **{**v, "usd": round(v["usd"], 4)}} for k, v in agents.items()), key=lambda a: -a["usd"]
    )
    return {
        "key": item,
        "name": first.name if first else item.split(":", 1)[-1],
        "kind": first.kind if first else None,
        "project": first.project if first else None,
        "range": win.range,
        "bucket_seconds": int(win.bucket.total_seconds()),
        "total_usd": round(total, 4),
        "tokens": sum(int(r.tokens or 0) for r in rows),
        "calls": len(rows),
        "timeline": [{"start": b.isoformat(), "usd": round(v, 4)} for b, v in zip(starts, timeline, strict=True)],
        "agents": sub_agents,
        "models": sorted(({**m, "usd": round(m["usd"], 4)} for m in models.values()), key=lambda m: -m["usd"]),
        "top_calls": [
            {"at": r.ts.isoformat(), "model": r.model, "agent": r.agent_name or "main session",
             "tokens": int(r.tokens or 0), "usd": round(float(r.usd or 0), 4)}
            for r in top
        ],
        "runs": (
            {
                "count": len(runs),
                "cost_per_run": round(total / len(runs), 4) if runs else 0.0,
                "median_run": round(median(runs.values()), 4) if runs else 0.0,
                "per_day": round(len(runs) / days, 2),
            }
            if is_job else None
        ),
    }


# ------------------------------------------------------------------ runaway spend alert

_HOURLY_SQL = text(
    f"""
    WITH {_SPEND_CTE}
    SELECT date_trunc('hour', ts) AS h, CASE WHEN kind = 'routine' THEN item END AS job, max(name) AS name,
           sum(usd) AS usd
    FROM spend GROUP BY 1, 2
    """
)
ALERT_HISTORY_DAYS = 14
ALERT_MIN_HISTORY_DAYS = 3
JOB_ALERT_RATIO = 3.0
JOB_ALERT_FLOOR_USD = 5.0
RATE_ALERT_RATIO = 2.0
RATE_ALERT_FLOOR_USD = 10.0
PUBLIC_COSTS_URL = "https://agent.summitflow.dev/costs"


@dataclass(frozen=True)
class SpendAlert:
    key: str
    message: str
    open_url: str


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0.0


def evaluate_spend_alerts(rows: list[tuple[datetime, str | None, str | None, float]], now: datetime) -> list[SpendAlert]:
    """Compare the last day (per routine job) and the last hour (everything) with their own history.

    rows: (hour, job item or None, job name, usd). No alert without ALERT_MIN_HISTORY_DAYS of history.
    """
    from urllib.parse import quote

    hour_now = now.replace(minute=0, second=0, microsecond=0)
    first_hour = min((h for h, *_ in rows), default=now)
    alerts: list[SpendAlert] = []
    totals: dict[datetime, float] = defaultdict(float)
    jobs: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[str, str] = {}
    for h, job, name, usd in rows:
        totals[h] += usd
        if job:
            jobs[job][int((now - h) / timedelta(days=1))] += usd
            names[job] = name or job
    history_days = (now - first_hour) / timedelta(days=1)
    if history_days < ALERT_MIN_HISTORY_DAYS + 1:
        return alerts
    for job, by_day in jobs.items():
        last_day = by_day.get(0, 0.0)
        prior = [v for d, v in by_day.items() if 1 <= d <= ALERT_HISTORY_DAYS and v > 0]
        if last_day < JOB_ALERT_FLOOR_USD or len(prior) < ALERT_MIN_HISTORY_DAYS:
            continue
        normal = median(prior)
        if last_day >= JOB_ALERT_RATIO * normal:
            url = f"{PUBLIC_COSTS_URL}?range=7d&item={quote(job, safe='')}"
            alerts.append(SpendAlert(
                key=f"spend-job:{job[:120]}",
                message=(f"{names[job]} spent ${last_day:,.0f} in the last 24 hours, about "
                         f"{last_day / normal:.0f}x its usual day (${normal:,.0f}). {url}"),
                open_url=url,
            ))
    last_hour = max(totals.get(hour_now - timedelta(hours=1), 0.0), totals.get(hour_now, 0.0))
    prior_hours = [
        totals.get(hour_now - timedelta(hours=k), 0.0) for k in range(2, ALERT_HISTORY_DAYS * 24)
        if hour_now - timedelta(hours=k) >= first_hour
    ]
    usual = _p95(prior_hours)
    if last_hour >= max(RATE_ALERT_RATIO * usual, RATE_ALERT_FLOOR_USD):
        url = f"{PUBLIC_COSTS_URL}?range=24h"
        alerts.append(SpendAlert(
            key="spend-rate",
            message=(f"Agents spent ${last_hour:,.0f} in the last hour; even a busy hour is usually under "
                     f"${usual:,.0f}. {url}"),
            open_url=url,
        ))
    return alerts


async def spend_alerts(db: AsyncSession, now: datetime | None = None) -> list[SpendAlert]:
    now = now or datetime.now(UTC)
    rows = (await db.execute(_HOURLY_SQL, _params(now - timedelta(days=ALERT_HISTORY_DAYS + 1), now))).all()
    return evaluate_spend_alerts([(h, job, name, float(usd or 0)) for h, job, name, usd in rows], now)
