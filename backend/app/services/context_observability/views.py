"""Read views for the Context pages: the Cost matrix, a cell's trend over time and a cell's latest start.

Everything is computed from the first-turn rows (usage_sessions), the delivery blocks and the markers view; nothing is
stored. A value that was not measured is None, never zero. A cell is one (harness, role) of the Cost matrix, or the
role group "lane" (see steps.ROLE_GROUPS). Medians are the upper median used everywhere else (baseline.med).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageSession

from .baseline import FirstTurn, load_first_turns, med
from .budgets import CellState, cell_states
from .markers import view_markers
from .policy import Policy, load_policy
from .steps import cell_rows, find_steps
from .why import explain

MIN_N = 3  # starts needed on each side of a comparison; fewer shows the median but no change
MAX_POINTS = 2000  # per-start dots the trend returns; more are thinned evenly
MAX_STEPS = 12  # steps explained per trend (newest)
MAX_STEP_MARKERS = 6
CELL_LOOKBACK_DAYS = 30
RECENT_STARTS = 10
PART_NAMES = ("harness_core", "harness_tools", "our_listings", "ours", "ah_global", "ah_role", "ah_project", "brief", "harness")


async def _earliest(db: AsyncSession) -> datetime | None:
    """The oldest measured first turn: how far back the data really goes, whatever window a page asks for."""
    stmt = select(func.min(UsageSession.first_turn_at)).where(UsageSession.first_turn_tokens.is_not(None))
    return (await db.execute(stmt)).scalar_one_or_none()


def _dominant(values: list[str | None]) -> str | None:
    known = [v for v in values if v]
    return Counter(known).most_common(1)[0][0] if known else None


def _change(now_total: int | None, before: int | None) -> tuple[int | None, float | None]:
    if now_total is None or not before:
        return None, None
    return now_total - before, (now_total - before) / before * 100


class MatrixCell(BaseModel):
    harness: str
    cell: str
    n: int
    total: int | None
    harness_tokens: int | None
    ours: int | None
    brief: int | None
    prev_n: int
    prev_total: int | None
    delta: int | None  # window median against the previous window of the same length, same model
    delta_pct: float | None
    latest_at: datetime
    version: str | None
    model: str | None
    warn_tokens: int | None
    jump_pct: int | None
    flag: str | None  # warn | jump: the budget state of the last 24 h (the Nightshift alert's own rule)
    recent: int | None  # last-24 h median that the flag is about
    n_recent: int


class HarnessInfo(BaseModel):
    harness: str
    version: str | None
    latest_at: datetime
    n: int


class Matrix(BaseModel):
    days: int
    generated_at: datetime
    coverage_from: datetime | None  # the oldest measured start overall; younger than the window means the data does not reach back that far
    jump_pct: int | None
    harnesses: list[HarnessInfo]
    cells: list[MatrixCell]


def build_matrix(rows: list[FirstTurn], policy: Policy, states: list[CellState], *, days: int, now: datetime,
                 coverage_from: datetime | None = None) -> Matrix:
    """rows: first turns from now - 2 * days (the second half is the comparison window)."""
    edge, old = now - timedelta(days=days), now - timedelta(days=2 * days)
    state_by = {(s.harness, s.cell): s for s in states}
    groups: dict[tuple[str, str], list[FirstTurn]] = {}
    for row in rows:
        groups.setdefault((row.harness, row.cell), []).append(row)
    cells = []
    for (harness, cell), items in sorted(groups.items()):
        window = [r for r in items if r.at >= edge]
        if not window:
            continue
        model = _dominant([r.model for r in window])
        win_same = [r for r in window if r.model == model]
        prev_same = [r for r in items if old <= r.at < edge and r.model == model]
        prev_total = med(r.total for r in prev_same)
        delta, pct = (None, None)
        if len(win_same) >= MIN_N and len(prev_same) >= MIN_N:
            delta, pct = _change(med(r.total for r in win_same), prev_total)
        budget = policy.budget_for(harness, cell)
        state = state_by.get((harness, cell))
        newest = max(window, key=lambda r: r.at)
        cells.append(MatrixCell(
            harness=harness, cell=cell, n=len(window), total=med(r.total for r in window),
            harness_tokens=med(r.harness_tokens for r in window), ours=med(r.ours_tokens for r in window),
            brief=med(r.brief_tokens for r in window), prev_n=len(prev_same), prev_total=prev_total, delta=delta, delta_pct=pct,
            latest_at=newest.at, version=newest.version, model=model, warn_tokens=budget.warn_tokens if budget else None,
            jump_pct=policy.jump_pct, flag=state.reason if state else None, recent=state.recent if state else None,
            n_recent=state.n_recent if state else 0))
    latest: dict[str, FirstTurn] = {}
    first_seen: dict[str, dict[str, datetime]] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        if row.at < edge:
            continue
        counts[row.harness] += 1
        if row.harness not in latest or row.at > latest[row.harness].at:
            latest[row.harness] = row
        if row.version:
            seen = first_seen.setdefault(row.harness, {})
            seen[row.version] = min(row.at, seen.get(row.version, row.at))
    # The version in use is the one that appeared last: sub-agents and resumed sessions keep older ones alive.
    harnesses = [HarnessInfo(harness=h, version=max(first_seen[h], key=lambda v: first_seen[h][v]) if h in first_seen else None,
                             latest_at=r.at, n=counts[h]) for h, r in sorted(latest.items())]
    return Matrix(days=days, generated_at=now, coverage_from=coverage_from or min((r.at for r in rows), default=None), jump_pct=policy.jump_pct,
                  harnesses=harnesses, cells=cells)


async def matrix(db: AsyncSession, *, days: int, now: datetime | None = None) -> Matrix:
    now = now or datetime.now(UTC)
    policy = await load_policy(db)
    rows = await load_first_turns(db, since=now - timedelta(days=2 * days), until=now)
    return build_matrix(rows, policy, await cell_states(db, now=now, policy=policy), days=days, now=now,
                        coverage_from=await _earliest(db))


# --- trend ---------------------------------------------------------------------------------------------------------


class TrendPoint(BaseModel):
    at: datetime
    total: int
    harness_tokens: int | None
    ours: int | None
    brief: int | None
    version: str | None
    model: str | None


class TrendDay(BaseModel):
    day: str  # UTC date
    n: int
    total: int | None
    harness_tokens: int | None
    ours: int | None
    brief: int | None


class VersionSighting(BaseModel):
    version: str
    first_at: datetime
    n: int
    initial: bool  # already running at the start of the window, so not a change inside it


class StepMarker(BaseModel):
    at: datetime
    kind: str
    label: str


class TrendStep(BaseModel):
    at: datetime
    kind: str  # config | version | day: what the step finder saw
    cause: str  # ours | config | harness_version | harness | model | brief | none: what `why` blames
    model: str | None
    delta: int
    pct: float
    before_total: int | None
    after_total: int | None
    n_before: int
    n_after: int
    parts: dict[str, int | None]
    summary: str
    markers: list[StepMarker]


class TrendHeadline(BaseModel):
    n: int
    total: int | None
    harness_tokens: int | None
    ours: int | None
    brief: int | None
    prev_n: int
    prev_total: int | None
    delta: int | None
    delta_pct: float | None


class Trend(BaseModel):
    harness: str
    role: str
    days: int
    generated_at: datetime
    coverage_from: datetime | None  # the oldest measured start of this cell
    latest_at: datetime | None
    jump_pct: int | None
    warn_tokens: int | None
    headline: TrendHeadline
    points: list[TrendPoint]
    points_total: int
    daily: list[TrendDay]
    versions: list[VersionSighting]
    steps: list[TrendStep]


def _thin(items: list[Any], limit: int) -> list[Any]:
    if len(items) <= limit:
        return items
    stride = len(items) / limit
    return [items[int(i * stride)] for i in range(limit)]


def daily_series(rows: list[FirstTurn]) -> list[TrendDay]:
    by_day: dict[str, list[FirstTurn]] = {}
    for row in rows:
        by_day.setdefault(row.at.astimezone(UTC).date().isoformat(), []).append(row)
    return [TrendDay(day=day, n=len(items), total=med(r.total for r in items), harness_tokens=med(r.harness_tokens for r in items),
                     ours=med(r.ours_tokens for r in items), brief=med(r.brief_tokens for r in items))
            for day, items in sorted(by_day.items())]


def version_sightings(rows: list[FirstTurn]) -> list[VersionSighting]:
    """First start of each harness version in the window, oldest first. The first one is the version already running."""
    firsts: dict[str, datetime] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        if not row.version:
            continue
        counts[row.version] += 1
        if row.version not in firsts or row.at < firsts[row.version]:
            firsts[row.version] = row.at
    ordered = sorted(firsts.items(), key=lambda kv: kv[1])
    return [VersionSighting(version=v, first_at=at, n=counts[v], initial=i == 0) for i, (v, at) in enumerate(ordered)]


def headline(window: list[FirstTurn], previous: list[FirstTurn]) -> TrendHeadline:
    model = _dominant([r.model for r in window])
    win_same = [r for r in window if r.model == model]
    prev_same = [r for r in previous if r.model == model]
    prev_total = med(r.total for r in prev_same)
    delta, pct = (None, None)
    if len(win_same) >= MIN_N and len(prev_same) >= MIN_N:
        delta, pct = _change(med(r.total for r in win_same), prev_total)
    return TrendHeadline(
        n=len(window), total=med(r.total for r in window), harness_tokens=med(r.harness_tokens for r in window),
        ours=med(r.ours_tokens for r in window), brief=med(r.brief_tokens for r in window), prev_n=len(prev_same),
        prev_total=prev_total, delta=delta, delta_pct=pct)


async def trend(db: AsyncSession, harness: str, role: str, *, days: int, now: datetime | None = None) -> Trend:
    now = now or datetime.now(UTC)
    policy = await load_policy(db)
    edge = now - timedelta(days=days)
    old = now - timedelta(days=2 * days)
    # One day more than the comparison needs, so "the data starts here" is only claimed when it really does.
    rows = cell_rows(await load_first_turns(db, since=old - timedelta(days=1), until=now, harness=harness), harness, role)
    window = [r for r in rows if r.at >= edge]
    previous = [r for r in rows if old <= r.at < edge]
    points = _thin(window, MAX_POINTS)
    steps: list[TrendStep] = []
    if policy.jump_pct is not None and window:
        for step in find_steps(window, policy.jump_pct)[-MAX_STEPS:]:
            why = await explain(db, rows, harness, role, step.at, policy=policy, now=now, kind=step.kind, model=step.model)
            marks = sorted(why.markers, key=lambda m: (m.kind in ("memory", "prompt"), m.at))[:MAX_STEP_MARKERS]
            steps.append(TrendStep(
                at=step.at, kind=step.kind, cause=why.cause, model=step.model, delta=step.delta, pct=step.pct,
                before_total=step.before.total, after_total=step.after.total, n_before=step.before.n, n_after=step.after.n,
                parts=why.parts, summary=why.summary,
                markers=[StepMarker(at=m.at, kind=m.kind, label=m.label[:80]) for m in sorted(marks, key=lambda m: m.at)]))
    budget = policy.budget_for(harness, role)
    return Trend(
        harness=harness, role=role, days=days, generated_at=now, coverage_from=min((r.at for r in rows), default=None),
        latest_at=max((r.at for r in rows), default=None), jump_pct=policy.jump_pct, warn_tokens=budget.warn_tokens if budget else None,
        headline=headline(window, previous),
        points=[TrendPoint(at=r.at, total=r.total, harness_tokens=r.harness_tokens, ours=r.ours_tokens, brief=r.brief_tokens,
                           version=r.version, model=r.model) for r in points],
        points_total=len(window), daily=daily_series(window), versions=version_sightings(window), steps=steps)


# --- cell ----------------------------------------------------------------------------------------------------------


class PartValue(BaseModel):
    tokens: int | None
    method: str | None


class CellBlock(BaseModel):
    block_id: str
    source_type: str
    source_id: str
    label: str
    kind: str | None
    scope: str | None
    tokens: int
    revision: str | None
    writer_at: datetime | None  # newest revision in the last 30 days; None when none or older
    writer_kind: str | None
    writer_session: str | None
    writer_action: str | None


class CellStart(BaseModel):
    at: datetime
    session_id: str
    total: int
    harness_tokens: int | None
    ours: int | None
    brief: int | None
    version: str | None
    model: str | None
    launch_mode: str


class CellGrowth(BaseModel):
    sessions: int  # starts in the lookback
    measured: int  # of those, sessions with a peak read from usage_calls
    median_peak: int | None
    max_peak: int | None
    median_first_turn: int | None  # first turn of the measured sessions, to read the peak against
    compacted: int  # sessions that compacted at least once
    compactions: int


class CellLatestMove(BaseModel):
    at: datetime
    kind: str
    cause: str
    delta: int | None
    pct: float | None
    summary: str


class CellView(BaseModel):
    harness: str
    role: str
    generated_at: datetime
    lookback_days: int
    latest: CellStart | None
    config_fp: str | None
    delivery_id: str | None
    parts: dict[str, PartValue]
    blocks: list[CellBlock]
    blocks_total: int | None  # sum of block tokens, as delivered
    budget_warn: int | None
    budget_jump_pct: int | None
    state: CellState | None
    growth: CellGrowth
    latest_move: CellLatestMove | None
    recent: list[CellStart]


def _start(row: FirstTurn) -> CellStart:
    return CellStart(at=row.at, session_id=row.session_id, total=row.total, harness_tokens=row.harness_tokens, ours=row.ours_tokens,
                     brief=row.brief_tokens, version=row.version, model=row.model, launch_mode=row.launch_mode)


async def _block_labels(db: AsyncSession, blocks: list[dict[str, Any]]) -> dict[str, str]:
    ids = [str(b.get("source_id")) for b in blocks if b.get("source_type") == "memory"]
    if not ids:
        return {}
    found = (await db.execute(text(
        "SELECT CAST(id AS text) AS id, COALESCE(NULLIF(summary, ''), name) AS label FROM memories WHERE CAST(id AS text) = ANY(:ids)"
    ), {"ids": ids})).all()
    return {r.id: str(r.label)[:100] for r in found if r.label}


async def _delivery_blocks(db: AsyncSession, delivery_id: str | None, now: datetime) -> list[CellBlock]:
    if not delivery_id:
        return []
    found = (await db.execute(text("SELECT blocks FROM context_deliveries WHERE delivery_id = :id"), {"id": delivery_id})).first()
    raw = [b for b in (found.blocks if found else None) or [] if isinstance(b, dict)]
    if not raw:
        return []
    labels = await _block_labels(db, raw)
    writers = {}
    for marker in await view_markers(db, now - timedelta(days=CELL_LOOKBACK_DAYS), now, kinds=("memory", "prompt")):
        writers[marker.ref] = marker  # oldest first, so the newest wins
    out = []
    for block in raw:
        source_id = str(block.get("source_id"))
        marker = writers.get(source_id)
        revision = block.get("revision")
        out.append(CellBlock(
            block_id=str(block.get("block_id")), source_type=str(block.get("source_type")), source_id=source_id,
            label=labels.get(source_id) or (marker.label[:100] if marker else source_id), kind=block.get("kind"), scope=block.get("scope"),
            tokens=int(block.get("tokens") or 0), revision=None if revision is None else str(revision),
            writer_at=marker.at if marker else None, writer_kind=marker.detail.get("writer_kind") if marker else None,
            writer_session=marker.detail.get("writer_session") if marker else None, writer_action=marker.detail.get("action") if marker else None))
    return sorted(out, key=lambda b: -b.tokens)


def _growth(rows: list[FirstTurn], sessions: list[UsageSession]) -> CellGrowth:
    keys = {(r.provider, r.session_id, r.agent_id) for r in rows}
    mine = [s for s in sessions if (s.provider, s.session_id, s.agent_id) in keys]
    measured = [s for s in mine if s.peak_context_tokens is not None]
    return CellGrowth(
        sessions=len(rows), measured=len(measured), median_peak=med(int(s.peak_context_tokens) for s in measured if s.peak_context_tokens is not None),
        max_peak=max((int(s.peak_context_tokens) for s in measured if s.peak_context_tokens is not None), default=None),
        median_first_turn=med(s.first_turn_tokens for s in measured),
        compacted=sum(1 for s in measured if (s.compaction_count or 0) > 0), compactions=sum(s.compaction_count or 0 for s in measured))


async def cell(db: AsyncSession, harness: str, role: str, *, now: datetime | None = None) -> CellView:
    now = now or datetime.now(UTC)
    policy = await load_policy(db)
    since = now - timedelta(days=CELL_LOOKBACK_DAYS)
    rows = cell_rows(await load_first_turns(db, since=since, until=now, harness=harness), harness, role)
    budget = policy.budget_for(harness, role)
    state = next((s for s in await cell_states(db, now=now, policy=policy) if s.harness == harness and s.cell == role), None)
    empty = CellView(harness=harness, role=role, generated_at=now, lookback_days=CELL_LOOKBACK_DAYS, latest=None, config_fp=None,
                     delivery_id=None, parts={}, blocks=[], blocks_total=None, budget_warn=budget.warn_tokens if budget else None,
                     budget_jump_pct=policy.jump_pct, state=state, growth=_growth([], []), latest_move=None, recent=[])
    if not rows:
        return empty
    latest = rows[-1]
    session = (await db.execute(select(UsageSession).where(
        UsageSession.provider == latest.provider, UsageSession.session_id == latest.session_id, UsageSession.agent_id == latest.agent_id,
    ))).scalar_one_or_none()
    stored = (session.parts if session else None) or {}
    parts = {name: PartValue(tokens=(stored[name] or {}).get("tokens"), method=(stored[name] or {}).get("method"))
             for name in PART_NAMES if isinstance(stored.get(name), dict)}
    sessions = (await db.execute(select(UsageSession).where(
        UsageSession.harness == harness, UsageSession.first_turn_at >= since, UsageSession.first_turn_tokens.is_not(None),
    ))).scalars().all()
    blocks = await _delivery_blocks(db, latest.delivery_id, now)
    move = None
    if policy.jump_pct is not None:
        found = find_steps(rows, policy.jump_pct)
        if found:
            step = found[-1]
            why = await explain(db, rows, harness, role, step.at, policy=policy, now=now, kind=step.kind, model=step.model)
            move = CellLatestMove(at=step.at, kind=step.kind, cause=why.cause, delta=why.delta, pct=why.pct, summary=why.summary)
    return empty.model_copy(update={
        "latest": _start(latest), "config_fp": latest.config_fp, "delivery_id": latest.delivery_id, "parts": parts, "blocks": blocks,
        "blocks_total": sum(b.tokens for b in blocks) if blocks else None, "growth": _growth(rows, list(sessions)), "latest_move": move,
        "recent": [_start(r) for r in reversed(rows[-RECENT_STARTS:])]})
