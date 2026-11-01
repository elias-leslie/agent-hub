"""Pi sessions, Agent Hub's own agents and per-session growth: the sources M1a's Claude/Codex capture does not reach.

Pi sessions and Agent Hub sessions get their own usage_sessions rows (provider "pi" / "agent_hub", no usage_calls),
first-turn columns filled the same way as Claude and Codex. Peak context and compaction count come from usage_calls.
`backfill_extra` is part of the 30-day backfill; `capture_pass` is what the collector runs every pass, from a watermark
kept in subscription_usage_cursors so an outage longer than the live lookback loses nothing (up to the backfill window).
A first turn is measured once: a rerun keeps what a row already holds. Each stage and each row has its own savepoint, so
one bad session or one failing stage never costs the others (or the caller's transaction).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextDelivery, SubscriptionUsageCursor, UsageSession
from app.utils.native_homes import pi_session_roots

from . import agent_hub_turn, first_turn, growth, pi_turn
from .deliveries import _row_dict

logger = logging.getLogger(__name__)

PI_PROVIDER = "pi"
LIVE_LOOKBACK = timedelta(hours=2)  # each pass reads this far behind its watermark: a row that committed late still lands
MAX_CATCHUP = timedelta(days=30)  # the backfill window: a longer outage is the backfill's job
WATERMARK_PATH = "@context_extra"
_FIRST_TURN_COLUMNS = (
    "harness", "harness_version", "work_role", "coordinator", "launch_mode", "model", "first_turn_tokens", "first_turn_at",
    "parts", "delivery_id", "config_fp",
)


def _upsert(values: dict[str, Any]):
    """Insert a session row, or on conflict extend its times and fill the first-turn columns only if it has none yet.

    A first turn never changes, but what a rerun can compute does: a backfill run today would stamp today's `pi --version`
    and prompt stack on an older row. So a row that already holds a measured first turn keeps all of its first-turn columns.
    """
    stmt = pg_insert(UsageSession).values(values)
    ex = stmt.excluded
    unmeasured = UsageSession.first_turn_tokens.is_(None)
    set_ = {c: case((unmeasured, ex[c]), else_=getattr(UsageSession, c)) for c in _FIRST_TURN_COLUMNS}
    set_["first_at"] = func.least(UsageSession.first_at, ex.first_at)
    set_["last_at"] = func.greatest(UsageSession.last_at, ex.last_at)
    return stmt.on_conflict_do_update(index_elements=["provider", "session_id", "agent_id"], set_=set_)


def _project(cwd: str | None) -> str:
    from app.services.subscription_accounting.collector import project_from_cwd

    return project_from_cwd(cwd)


# ------------------------------------------------------------------ Pi


def pi_session_id(path: Path) -> str:
    """Pi names a session file <timestamp>_<session id>.jsonl."""
    return path.stem.rsplit("_", 1)[-1]


def pi_files_since(since: float) -> list[Path]:
    found = []
    for root in pi_session_roots():
        if not root.is_dir():
            continue
        for path in root.glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime >= since:
                    found.append(path)
            except OSError:
                continue
    return sorted(found)


def read_pi_heads(paths: list[Path], *, since: datetime, until: datetime | None) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for path in paths:
        try:
            raw = pi_turn.read_pi_head(path)
        except Exception as exc:  # one odd session file must not stop the rest
            logger.warning("pi first turn unreadable %s: %s: %s", path, type(exc).__name__, (str(exc).splitlines() or [""])[0][:200])
            continue
        if raw and raw["first_at"] >= since and (until is None or raw["first_at"] <= until):
            out.append((path, raw))
    return out


def _pi_fits(delivery: ContextDelivery, raw: dict[str, Any]) -> bool:
    """A delivery bigger than the first turn minus the brief cannot be in it (the harness part would derive to 0)."""
    brief = first_turn.est_tokens(int(raw.get("brief_chars") or 0))
    return int(delivery.est_tokens) <= int(raw["total"]) - brief


async def assign_pi_deliveries(db: AsyncSession, heads: list[tuple[Path, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Pi session id -> the delivery built for it, one delivery per session.

    Pi sessions carry no delivery id, so time is the only link: a local pi delivery that landed from
    PI_BIND_BEFORE before to PI_BIND_AFTER after the session record and fits its first turn. Pairs are taken greedily,
    the same project first and then the closest in time, and a delivery serves one session: fleets that launch seconds
    apart would otherwise share one. Sessions that already hold a first turn keep it, and their deliveries are taken.
    Blank-slate launches get no delivery.
    """
    candidates = [(path, raw) for path, raw in heads if pi_turn.launch_mode(path, raw.get("cwd")) != "blank"]
    if not candidates:
        return {}
    starts = [raw["started"] for _, raw in candidates]
    rows = (await db.execute(
        select(ContextDelivery).where(
            ContextDelivery.surface == "pi", ContextDelivery.host.is_(None),
            ContextDelivery.generated_at >= min(starts) - pi_turn.PI_BIND_BEFORE,
            ContextDelivery.generated_at <= max(starts) + pi_turn.PI_BIND_AFTER,
        )
    )).scalars().all()
    if not rows:
        return {}
    held = set((await db.execute(
        select(UsageSession.session_id).where(
            UsageSession.provider == PI_PROVIDER, UsageSession.first_turn_tokens.is_not(None),
            UsageSession.session_id.in_([raw["sid"][:100] for _, raw in candidates]),
        )
    )).scalars())
    taken = set((await db.execute(
        select(UsageSession.delivery_id).where(UsageSession.provider == PI_PROVIDER, UsageSession.delivery_id.in_([d.delivery_id for d in rows]))
    )).scalars())
    pairs = []
    for _, raw in candidates:
        sid = raw["sid"][:100]
        if sid in held:
            continue
        project = _project(raw.get("cwd"))
        for d in rows:
            gap = (d.generated_at - raw["started"]).total_seconds()
            if -pi_turn.PI_BIND_BEFORE.total_seconds() <= gap <= pi_turn.PI_BIND_AFTER.total_seconds() and _pi_fits(d, raw):
                pairs.append((d.project_id != project, abs(gap), sid, d))
    pairs.sort(key=lambda p: (p[0], p[1], p[2], p[3].delivery_id))
    assigned: dict[str, dict[str, Any]] = {}
    for _, _, sid, d in pairs:
        if sid in assigned or d.delivery_id in taken:
            continue
        assigned[sid] = _row_dict(d)
        taken.add(d.delivery_id)
    return assigned


async def apply_pi(
    db: AsyncSession, heads: list[tuple[Path, dict[str, Any]]], *, now: datetime, version: str | None
) -> int:
    assigned = await assign_pi_deliveries(db, heads)
    n = 0
    for path, raw in heads:
        try:
            async with db.begin_nested():
                await _apply_pi_one(db, path, raw, assigned.get(raw["sid"][:100]), now=now, version=version)
        except Exception as exc:  # one odd session must not stop the rest
            logger.warning("pi first turn not stored %s: %s: %s", path, type(exc).__name__, (str(exc).splitlines() or [""])[0][:200])
            continue
        n += 1
    return n


async def _apply_pi_one(
    db: AsyncSession, path: Path, raw: dict[str, Any], delivery: dict[str, Any] | None, *, now: datetime, version: str | None
) -> None:
    sid = raw["sid"][:100]
    launch = pi_turn.launch_mode(path, raw.get("cwd"))
    parts = pi_turn.compute_parts(raw, delivery=delivery, launch=launch)
    basis = pi_turn.version_basis(raw["started"], now) if version else "unknown"
    parts["version_basis"] = basis
    if basis == pi_turn.VERSION_BASIS_BACKFILL:
        parts["installed_version"] = version  # what was installed at the backfill: not the version the session ran
        version = None  # harness_version is only ever a version seen while the session ran
    try:
        last = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        last = raw["first_at"]
    await db.execute(_upsert({
        "provider": PI_PROVIDER, "session_id": sid, "agent_id": "", "project": _project(raw.get("cwd"))[:200], "kind": "other",
        "first_at": raw["started"], "last_at": max(last, raw["first_at"]), "harness": PI_PROVIDER, "harness_version": version,
        "work_role": delivery["work_role"] if delivery else None, "coordinator": delivery["coordinator"] if delivery else None,
        "launch_mode": launch[:80], "model": (raw.get("model") or None) and str(raw["model"])[:100],
        "first_turn_tokens": int(raw["total"]), "first_turn_at": raw["first_at"], "parts": parts,
        "delivery_id": delivery["delivery_id"] if delivery else None, "config_fp": None,
    }))


async def capture_pi(db: AsyncSession, *, since: datetime, until: datetime | None, now: datetime, skip_done: bool) -> dict[str, int]:
    paths = await asyncio.to_thread(pi_files_since, since.timestamp())
    if skip_done and paths:
        ids = {pi_session_id(p) for p in paths}
        done = set((await db.execute(
            select(UsageSession.session_id).where(
                UsageSession.provider == PI_PROVIDER, UsageSession.session_id.in_(ids), UsageSession.first_turn_tokens.is_not(None)
            )
        )).scalars())
        paths = [p for p in paths if pi_session_id(p) not in done]
    heads = await asyncio.to_thread(read_pi_heads, paths, since=since, until=until)
    if not heads:
        return {"pi_read": 0, "pi_updated": 0}
    version = await asyncio.to_thread(pi_turn.installed_version)
    return {"pi_read": len(heads), "pi_updated": await apply_pi(db, heads, now=now, version=version)}


# ------------------------------------------------------------------ Agent Hub agents


async def bound_agent_delivery(db: AsyncSession, session_id: str) -> dict[str, Any] | None:
    row = (await db.execute(
        select(ContextDelivery).where(ContextDelivery.session_id == session_id, ContextDelivery.source == "agent")
        .order_by(ContextDelivery.generated_at).limit(1)
    )).scalars().first()
    return _row_dict(row) if row else None


async def capture_agent_hub(
    db: AsyncSession, *, since: datetime, until: datetime | None, now: datetime, skip_done: bool
) -> dict[str, int]:
    calls = await agent_hub_turn.first_calls(db, since=since, until=until)
    if skip_done and calls:
        done = set((await db.execute(
            select(UsageSession.session_id).where(
                UsageSession.provider == agent_hub_turn.PROVIDER, UsageSession.session_id.in_([c["session_id"] for c in calls]),
                UsageSession.first_turn_tokens.is_not(None),
            )
        )).scalars())
        calls = [c for c in calls if c["session_id"] not in done]
    stacks: dict[str | None, str | None] = {}
    n = 0
    for call in calls:
        try:
            async with db.begin_nested():
                await _apply_agent_one(db, call, stacks, now=now)
        except Exception as exc:  # one odd session (or a stack that will not render) must not stop the rest
            logger.warning(
                "agent hub first turn not stored %s: %s: %s", call["session_id"], type(exc).__name__, (str(exc).splitlines() or [""])[0][:200]
            )
            continue
        n += 1
    return {"agent_hub_read": len(calls), "agent_hub_updated": n}


async def _apply_agent_one(db: AsyncSession, call: dict[str, Any], stacks: dict[str | None, str | None], *, now: datetime) -> None:
    slug = call.get("agent_slug")
    if slug not in stacks:
        stacks[slug] = await agent_hub_turn.stack_text(db, slug)  # not cached on failure: the next row of the slug tries again
    stack = stacks[slug]
    live = now - call["created_at"] <= timedelta(hours=1)
    delivery = await bound_agent_delivery(db, call["session_id"])
    parts = agent_hub_turn.compute_parts(call, stack=stack, delivery=delivery, stack_basis="live" if live else "as_of_backfill")
    total = int(call["input_tokens"]) + int(call["cache_read"]) + int(call["cache_write"])
    await db.execute(_upsert({
        "provider": agent_hub_turn.PROVIDER, "session_id": call["session_id"], "agent_id": "",
        "project": (call.get("project_id") or "unknown")[:200], "kind": "other", "first_at": call["created_at"],
        "last_at": call["created_at"], "harness": "agent_hub", "harness_version": None, "work_role": None, "coordinator": None,
        "launch_mode": agent_hub_turn.launch_mode_for(call), "model": (call["model"] or None) and str(call["model"])[:100],
        "first_turn_tokens": total, "first_turn_at": call["created_at"], "parts": parts,
        "delivery_id": delivery["delivery_id"] if delivery else None,
        "config_fp": agent_hub_turn.stack_fingerprint(stack) if live else None,
    }))


# ------------------------------------------------------------------ entry points


async def _stage(db: AsyncSession, name: str, work: Any) -> dict[str, int] | None:
    """Run one stage in its own savepoint: its failure is logged and costs only that stage (None), never the caller's transaction."""
    try:
        async with db.begin_nested():
            return await work
    except Exception as exc:
        logger.warning("context observability %s failed: %s: %s", name, type(exc).__name__, (str(exc).splitlines() or [""])[0][:200])
        return None


async def _watermark(db: AsyncSession) -> datetime | None:
    state = (await db.execute(select(SubscriptionUsageCursor.state).where(SubscriptionUsageCursor.path == WATERMARK_PATH))).scalar()
    try:
        return datetime.fromisoformat(str((state or {}).get("until")))
    except ValueError:
        return None


async def _store_watermark(db: AsyncSession, until: datetime) -> None:
    stmt = pg_insert(SubscriptionUsageCursor).values(path=WATERMARK_PATH, offset=0, state={"until": until.isoformat()})
    await db.execute(stmt.on_conflict_do_update(index_elements=["path"], set_={"state": stmt.excluded.state, "updated_at": func.now()}))


async def _stages(db: AsyncSession, stages: list[tuple[str, Any]]) -> dict[str, int]:
    """Every stage's counts merged; stages_failed counts the ones that raised (their counts are missing)."""
    summary: dict[str, int] = {}
    failed = 0
    for name, work in stages:
        result = await _stage(db, name, work)
        if result is None:
            failed += 1
        else:
            summary |= result
    summary["stages_failed"] = failed
    return summary


async def _growth(work: Any) -> dict[str, int]:
    return {"growth_updated": await work}


async def backfill_extra(db: AsyncSession, *, since: datetime, until: datetime | None, now: datetime) -> dict[str, int]:
    """Pi, Agent Hub agents and growth for the last backfill window. Idempotent: measured rows are kept as they are."""
    return await _stages(db, [
        ("pi capture", capture_pi(db, since=since, until=until, now=now, skip_done=False)),
        ("agent hub capture", capture_agent_hub(db, since=since, until=until, now=now, skip_done=False)),
        ("growth", _growth(growth.update_since(db, since))),
    ])


async def capture_pass(db: AsyncSession, *, touched: list[tuple[str, str]], now: datetime | None = None) -> dict[str, int]:
    """What the collector adds each pass: new Pi and Agent Hub first turns, growth for the sessions it just read.

    Reads from LIVE_LOOKBACK before the stored watermark (the last pass's start), so a collector that was down for
    longer than the lookback catches up on return, up to MAX_CATCHUP. The watermark moves with the caller's commit,
    and stays put while a stage fails, so the failed stage is read again next pass.
    """
    now = now or datetime.now(UTC)
    mark = await _watermark(db)
    since = max(min(now, mark or now) - LIVE_LOOKBACK, now - MAX_CATCHUP)
    summary = await _stages(db, [
        ("pi capture", capture_pi(db, since=since, until=None, now=now, skip_done=True)),
        ("agent hub capture", capture_agent_hub(db, since=since, until=None, now=now, skip_done=True)),
        ("growth", _growth(growth.update_sessions(db, touched))),
    ])
    if not summary["stages_failed"]:
        await _store_watermark(db, now)
    return summary


__all__ = ["backfill_extra", "capture_pass"]
