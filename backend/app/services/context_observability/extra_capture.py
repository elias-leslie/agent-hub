"""Pi sessions, Agent Hub's own agents and per-session growth: the sources M1a's Claude/Codex capture does not reach.

Pi sessions and Agent Hub sessions get their own usage_sessions rows (provider "pi" / "agent_hub", no usage_calls),
first-turn columns filled the same way as Claude and Codex. Peak context and compaction count come from usage_calls.
`backfill_extra` is part of the 30-day backfill; `capture_pass` is what the collector runs every pass.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextDelivery, UsageSession
from app.utils.native_homes import pi_session_roots

from . import agent_hub_turn, growth, pi_turn
from .deliveries import _row_dict

logger = logging.getLogger(__name__)

PI_PROVIDER = "pi"
LIVE_LOOKBACK = timedelta(hours=2)
_FIRST_TURN_COLUMNS = (
    "harness", "harness_version", "work_role", "coordinator", "launch_mode", "model", "first_turn_tokens", "first_turn_at",
    "parts", "delivery_id", "config_fp",
)


def _upsert(values: dict[str, Any]):
    stmt = pg_insert(UsageSession).values(values)
    ex = stmt.excluded
    set_ = {c: ex[c] for c in _FIRST_TURN_COLUMNS}
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
        except OSError:
            continue
        if raw and raw["first_at"] >= since and (until is None or raw["first_at"] <= until):
            out.append((path, raw))
    return out


async def find_pi_delivery(db: AsyncSession, raw: dict[str, Any]) -> dict[str, Any] | None:
    """The pi delivery built within seconds of the session's start, preferring its project.

    Pi sessions carry no delivery id, so time is the only link. Two sessions started together may share one delivery.
    """
    started = raw["started"]
    rows = (await db.execute(
        select(ContextDelivery).where(
            ContextDelivery.surface == "pi", ContextDelivery.generated_at >= started - pi_turn.PI_BIND_WINDOW,
            ContextDelivery.generated_at <= started + pi_turn.PI_BIND_WINDOW,
        )
    )).scalars().all()
    if not rows:
        return None
    project = _project(raw.get("cwd"))
    best = min(rows, key=lambda d: (d.project_id != project, abs((d.generated_at - started).total_seconds())))
    return _row_dict(best)


async def apply_pi(
    db: AsyncSession, heads: list[tuple[Path, dict[str, Any]]], *, now: datetime, version: str | None
) -> int:
    n = 0
    for path, raw in heads:
        sid = raw["sid"][:100]
        launch = pi_turn.launch_mode(path, raw.get("cwd"))
        delivery = None if launch == "blank" else await find_pi_delivery(db, raw)  # a blank-slate launch gets no delivery
        parts = pi_turn.compute_parts(raw, delivery=delivery, launch=launch)
        parts["version_basis"] = pi_turn.version_basis(raw["started"], now) if version else "unknown"
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
        n += 1
    return n


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
        slug = call.get("agent_slug")
        if slug not in stacks:
            stacks[slug] = await agent_hub_turn.stack_text(db, slug)
        live = now - call["created_at"] <= timedelta(hours=1)
        delivery = await bound_agent_delivery(db, call["session_id"])
        parts = agent_hub_turn.compute_parts(
            call, stack=stacks[slug], delivery=delivery, stack_basis="live" if live else "as_of_backfill"
        )
        total = int(call["input_tokens"]) + int(call["cache_read"]) + int(call["cache_write"])
        await db.execute(_upsert({
            "provider": agent_hub_turn.PROVIDER, "session_id": call["session_id"], "agent_id": "",
            "project": (call.get("project_id") or "unknown")[:200], "kind": "other", "first_at": call["created_at"],
            "last_at": call["created_at"], "harness": "agent_hub", "harness_version": None, "work_role": None, "coordinator": None,
            "launch_mode": agent_hub_turn.launch_mode_for(call), "model": (call["model"] or None) and str(call["model"])[:100],
            "first_turn_tokens": total, "first_turn_at": call["created_at"], "parts": parts,
            "delivery_id": delivery["delivery_id"] if delivery else None,
            "config_fp": agent_hub_turn.stack_fingerprint(stacks[slug]) if live else None,
        }))
        n += 1
    return {"agent_hub_read": len(calls), "agent_hub_updated": n}


# ------------------------------------------------------------------ entry points


async def backfill_extra(db: AsyncSession, *, since: datetime, until: datetime | None, now: datetime) -> dict[str, int]:
    """Pi, Agent Hub agents and growth for the last backfill window. Idempotent."""
    summary = await capture_pi(db, since=since, until=until, now=now, skip_done=False)
    summary |= await capture_agent_hub(db, since=since, until=until, now=now, skip_done=False)
    summary["growth_updated"] = await growth.update_since(db, since)
    return summary


async def capture_pass(db: AsyncSession, *, touched: list[tuple[str, str]], now: datetime | None = None) -> dict[str, int]:
    """What the collector adds each pass: new Pi and Agent Hub first turns, growth for the sessions it just read."""
    now = now or datetime.now(UTC)
    since = now - LIVE_LOOKBACK
    summary = await capture_pi(db, since=since, until=None, now=now, skip_done=True)
    summary |= await capture_agent_hub(db, since=since, until=None, now=now, skip_done=True)
    summary["growth_updated"] = await growth.update_sessions(db, touched)
    return summary


__all__ = ["backfill_extra", "capture_pass"]
