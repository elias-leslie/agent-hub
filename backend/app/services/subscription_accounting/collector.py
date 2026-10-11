"""Incremental collector for subscription CLI usage: Codex and Claude Code session logs.

Reads only bytes appended since the last pass (cursor per file, committed in the same transaction as
the rollups, so a pass is never double-counted). Produces:
- subscription_usage_daily: tokens, API-equivalent value and Codex credits drawn per day/model/project.
- subscription_usage_snapshots: 5h / weekly window readings (Codex rate_limits; Claude statusline file).
- credit_lots rows for balance increases that no configured lot explains (source=unclassified).

Codex credit draw: concurrent sessions report stale balances, so draws are measured against a running
minimum; an increase of at least LOT_MIN_CREDITS above it is a new lot (grant or purchase).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CreditLot,
    SubscriptionUsageCursor,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
)

from . import rates

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 40
CURSOR_RETAIN_DAYS = 45
LOT_MIN_CREDITS = 1000.0
SNAPSHOT_MIN_INTERVAL_S = 15 * 60
MAX_SEEN_IDS = 500
CODEX_CREDIT_STATE = "@codex_credits"
SNAPSHOT_STATE = "@snapshots"
CLAUDE_STATUSLINE_STATE = "@claude_statusline"
CLAUDE_WINDOWS = {"five_hour": 300, "seven_day": 10080}


def codex_root() -> Path:
    return Path(os.environ.get("AGENT_HUB_CODEX_SESSIONS", Path.home() / ".codex" / "sessions"))


def claude_root() -> Path:
    return Path(os.environ.get("AGENT_HUB_CLAUDE_PROJECTS", Path.home() / ".claude" / "projects"))


def claude_statusline_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "claude-usage" / "rate-limits.json"


def project_from_cwd(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    path = cwd.rstrip("/")
    for prefix in ("/srv/workspaces/projects/", "/srv/workspaces/", str(Path.home()) + "/"):
        if path.startswith(prefix):
            return path[len(prefix):].split("/", 1)[0] or "unknown"
    return Path(path).name or "unknown"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _local_day(ts: datetime) -> date:
    return ts.astimezone().date()


def _epoch(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value, UTC)
    return None


@dataclass
class Rollup:
    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    api_equiv_usd: float = 0.0
    unpriced_tokens: int = 0
    credits_drawn: float = 0.0


@dataclass
class BalanceEvent:
    ts: datetime
    balance: float
    model: str
    project: str
    speed: str


@dataclass
class SnapshotEvent:
    provider: str
    ts: datetime
    window_minutes: int
    used_percent: float
    resets_at: datetime | None
    plan_type: str | None
    credits_balance: float | None


@dataclass
class PassResult:
    rollups: dict[tuple[date, str, str, str, str], Rollup] = field(default_factory=lambda: defaultdict(Rollup))
    cursors: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)
    balances: list[BalanceEvent] = field(default_factory=list)
    snapshots: list[SnapshotEvent] = field(default_factory=list)
    files_read: int = 0
    bytes_read: int = 0


def _iter_new_lines(path: Path, offset: int) -> Iterator[tuple[int, bytes]]:
    """Yield (end_offset, line) for complete lines appended after offset."""
    with path.open("rb") as fh:
        fh.seek(offset)
        pos = offset
        for line in fh:
            if not line.endswith(b"\n"):
                return  # partial line still being written
            pos += len(line)
            yield pos, line


# ------------------------------------------------------------------ Codex


def _codex_file(path: Path, offset: int, state: dict[str, Any], result: PassResult) -> int:
    for end, line in _iter_new_lines(path, offset):
        offset = end
        head = line[:400]
        if b'"session_meta"' in head:
            with contextlib.suppress(ValueError):
                state["cwd"] = (json.loads(line).get("payload") or {}).get("cwd") or state.get("cwd")
            continue
        if b'"turn_context"' in head:
            try:
                payload = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            state["model"] = payload.get("model") or state.get("model")
            tier = payload.get("service_tier")
            state["speed"] = tier if isinstance(tier, str) and tier in rates.CODEX_SPEED_MULT else "standard"
            continue
        if b'"token_count"' not in head:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        payload = rec.get("payload") or {}
        ts = _parse_ts(rec.get("timestamp"))
        if payload.get("type") != "token_count" or ts is None:
            continue
        model = str(state.get("model") or "unknown")
        project = project_from_cwd(state.get("cwd"))
        speed = str(state.get("speed") or "standard")
        info = payload.get("info") or {}
        total = (info.get("total_token_usage") or {}).get("total_tokens")
        last = info.get("last_token_usage") or {}
        if last and total != state.get("last_total"):
            state["last_total"] = total
            _add_codex_tokens(result, ts, model, project, speed, last)
        _codex_rate_limits(result, ts, model, project, speed, payload.get("rate_limits") or {})
    return offset


def _add_codex_tokens(result: PassResult, ts: datetime, model: str, project: str, speed: str, last: dict) -> None:
    total_in = int(last.get("input_tokens") or 0)
    cached = int(last.get("cached_input_tokens") or 0)
    uncached = max(total_in - cached, 0)
    out = int(last.get("output_tokens") or 0)
    roll = result.rollups[(_local_day(ts), "codex", model, project, speed)]
    roll.requests += 1
    roll.input_tokens += uncached
    roll.cached_input_tokens += cached
    roll.output_tokens += out
    credits = rates.codex_credits(model, input_tokens=uncached, cached_input_tokens=cached, output_tokens=out, speed=speed)
    if credits is None:
        roll.unpriced_tokens += uncached + cached + out
    else:
        roll.api_equiv_usd += credits * rates.CREDIT_API_PARITY_USD


def _codex_rate_limits(
    result: PassResult, ts: datetime, model: str, project: str, speed: str, limits: dict
) -> None:
    if not limits:
        return
    credits = limits.get("credits") or {}
    balance: float | None = None
    try:
        if credits.get("balance") is not None and not credits.get("unlimited"):
            balance = float(credits["balance"])
    except (TypeError, ValueError):
        balance = None
    if balance is not None:
        result.balances.append(BalanceEvent(ts, balance, model, project, speed))
    for key in ("primary", "secondary"):
        window = limits.get(key) or {}
        minutes, used = window.get("window_minutes"), window.get("used_percent")
        if isinstance(minutes, int) and isinstance(used, (int, float)):
            result.snapshots.append(
                SnapshotEvent("codex", ts, minutes, float(used), _epoch(window.get("resets_at")),
                              limits.get("plan_type"), balance)
            )


# ------------------------------------------------------------------ Claude Code


def _claude_file(path: Path, offset: int, state: dict[str, Any], result: PassResult) -> int:
    seen: list[str] = state.setdefault("seen", [])
    seen_set = set(seen)
    for end, line in _iter_new_lines(path, offset):
        offset = end
        if b'"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            continue
        model = msg.get("model")
        ts = _parse_ts(rec.get("timestamp"))
        if not isinstance(model, str) or model.startswith("<") or ts is None:
            continue
        ident = f"{msg.get('id')}:{rec.get('requestId')}"
        if ident in seen_set:
            continue
        seen.append(ident)
        seen_set.add(ident)
        _add_claude_usage(result, ts, model, project_from_cwd(rec.get("cwd")), msg["usage"])
    del seen[:-MAX_SEEN_IDS]
    return offset


def _add_claude_usage(result: PassResult, ts: datetime, model: str, project: str, use: dict) -> None:
    inp = int(use.get("input_tokens") or 0)
    out = int(use.get("output_tokens") or 0)
    read = int(use.get("cache_read_input_tokens") or 0)
    write_total = int(use.get("cache_creation_input_tokens") or 0)
    split = use.get("cache_creation") or {}
    w5 = int(split.get("ephemeral_5m_input_tokens") or 0)
    w1h = int(split.get("ephemeral_1h_input_tokens") or 0)
    if not split:
        w1h = write_total  # Claude Code here uses the 1-hour TTL
    speed = use.get("speed") if use.get("speed") in rates.CLAUDE_SPEED_MULT else "standard"
    roll = result.rollups[(_local_day(ts), "claude", model, project, str(speed))]
    roll.requests += 1
    roll.input_tokens += inp
    roll.cached_input_tokens += read
    roll.cache_write_tokens += w5 + w1h
    roll.output_tokens += out
    usd = rates.claude_api_equiv_usd(
        model, input_tokens=inp, output_tokens=out, cache_read=read, cache_write_5m=w5, cache_write_1h=w1h,
        speed=str(speed), geo=use.get("inference_geo"),
    )
    if usd is None:
        roll.unpriced_tokens += inp + out + read + w5 + w1h
    else:
        roll.api_equiv_usd += usd


def _claude_statusline(state: dict[str, Any], result: PassResult) -> None:
    path = claude_statusline_file()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    observed = _epoch(data.get("observed_at"))
    limits = data.get("rate_limits") or {}
    if observed is None or not isinstance(limits, dict) or state.get("observed_at") == data.get("observed_at"):
        return
    state["observed_at"] = data.get("observed_at")
    for key, minutes in CLAUDE_WINDOWS.items():
        window = limits.get(key) or {}
        used = window.get("used_percentage")
        if isinstance(used, (int, float)):
            result.snapshots.append(
                SnapshotEvent("claude", observed, minutes, float(used), _epoch(window.get("resets_at")), None, None)
            )


# ------------------------------------------------------------------ pass


def _candidate_files(root: Path, pattern: str, since: float) -> list[Path]:
    if not root.is_dir():
        return []
    out = []
    for path in root.glob(pattern):
        try:
            if path.stat().st_mtime >= since:
                out.append(path)
        except OSError:
            continue
    return sorted(out)


def scan(cursors: dict[str, tuple[int, dict[str, Any]]], now: float | None = None) -> PassResult:
    """Read new log bytes (blocking; run in a thread). cursors: path -> (offset, state)."""
    now = now or time.time()
    since = now - BACKFILL_DAYS * 86400
    result = PassResult()
    jobs = [(p, _codex_file) for p in _candidate_files(codex_root(), "*/*/*/*.jsonl", since)]
    jobs += [(p, _claude_file) for p in _candidate_files(claude_root(), "**/*.jsonl", since)]
    for path, reader in jobs:
        key = str(path)
        offset, state = cursors.get(key, (0, {}))
        state = dict(state)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < offset:
            offset, state = 0, {}
        if size == offset:
            continue
        try:
            new_offset = reader(path, offset, state, result)
        except OSError as exc:
            logger.warning("subscription usage: cannot read %s: %s", path, exc)
            continue
        if new_offset != offset:
            result.files_read += 1
            result.bytes_read += new_offset - offset
            result.cursors[key] = (new_offset, state)
    statusline_state = dict(cursors.get(CLAUDE_STATUSLINE_STATE, (0, {}))[1])
    _claude_statusline(statusline_state, result)
    result.cursors[CLAUDE_STATUSLINE_STATE] = (0, statusline_state)
    return result


def apply_credit_draws(
    events: list[BalanceEvent], state: dict[str, Any], lot_times: list[datetime], result: PassResult
) -> list[tuple[datetime, float]]:
    """Fold balance reports into draws (running minimum). Returns unexplained increases (new lots)."""
    new_lots: list[tuple[datetime, float]] = []
    runmin = state.get("runmin")
    for ev in sorted(events, key=lambda e: e.ts):
        if runmin is None:
            runmin = ev.balance
            continue
        if ev.balance >= runmin + LOT_MIN_CREDITS:
            added = ev.balance - runmin
            if not any(abs((ev.ts - t).total_seconds()) < 3600 for t in lot_times):
                new_lots.append((ev.ts, added))
                lot_times.append(ev.ts)
            runmin = ev.balance
        elif ev.balance < runmin:
            result.rollups[(_local_day(ev.ts), "codex", ev.model, ev.project, ev.speed)].credits_drawn += runmin - ev.balance
            runmin = ev.balance
    state["runmin"] = runmin
    return new_lots


def select_snapshots(events: list[SnapshotEvent], state: dict[str, Any]) -> list[SnapshotEvent]:
    """Keep monotonic readings per provider/window: a newer window, a higher reading, or a periodic heartbeat."""
    keep: list[SnapshotEvent] = []
    for ev in sorted(events, key=lambda e: e.ts):
        key = f"{ev.provider}:{ev.window_minutes}"
        resets = ev.resets_at.timestamp() if ev.resets_at else 0.0
        prev = state.get(key)
        if prev:
            p_resets, p_used, p_ts, p_plan = prev
            if resets < p_resets - 60:
                continue  # stale session reporting an older window
            same_window = abs(resets - p_resets) <= 60
            if same_window and ev.used_percent <= p_used and ev.plan_type == p_plan and (
                ev.ts.timestamp() - p_ts < SNAPSHOT_MIN_INTERVAL_S
            ):
                continue
            if same_window and ev.used_percent < p_used:
                ev.used_percent = p_used  # stale lower reading inside the same window
        state[key] = [resets, ev.used_percent, ev.ts.timestamp(), ev.plan_type]
        keep.append(ev)
    return keep


_lock = asyncio.Lock()
_last_run = 0.0


async def collect(db: AsyncSession, *, min_interval_s: float = 300.0) -> dict[str, Any]:
    """Run one incremental pass unless one ran within min_interval_s. Commits its own transaction."""
    global _last_run
    if _lock.locked() or time.monotonic() - _last_run < min_interval_s:
        return {"skipped": True}
    async with _lock:
        _last_run = time.monotonic()
        rows = (await db.execute(select(SubscriptionUsageCursor))).scalars().all()
        cursors = {r.path: (int(r.offset), dict(r.state or {})) for r in rows}
        result = await asyncio.to_thread(scan, cursors)
        lots = (await db.execute(select(CreditLot).where(CreditLot.provider == "codex"))).scalars().all()
        credit_state = dict(cursors.get(CODEX_CREDIT_STATE, (0, {}))[1])
        new_lots = apply_credit_draws(result.balances, credit_state, [lot.granted_at for lot in lots], result)
        snap_state = dict(cursors.get(SNAPSHOT_STATE, (0, {}))[1])
        snapshots = select_snapshots(result.snapshots, snap_state)
        result.cursors[CODEX_CREDIT_STATE] = (0, credit_state)
        result.cursors[SNAPSHOT_STATE] = (0, snap_state)
        await _persist(db, result, snapshots, new_lots)
        await db.commit()
        return {"files_read": result.files_read, "bytes_read": result.bytes_read, "snapshots": len(snapshots),
                "new_lots": len(new_lots)}


async def _persist(
    db: AsyncSession, result: PassResult, snapshots: list[SnapshotEvent], new_lots: list[tuple[datetime, float]]
) -> None:
    for (day, provider, model, project, speed), r in result.rollups.items():
        values = {
            "day": day, "provider": provider, "model": model[:100], "project": project[:200], "speed": speed,
            "requests": r.requests, "input_tokens": r.input_tokens, "cached_input_tokens": r.cached_input_tokens,
            "cache_write_tokens": r.cache_write_tokens, "output_tokens": r.output_tokens,
            "api_equiv_usd": r.api_equiv_usd, "unpriced_tokens": r.unpriced_tokens, "credits_drawn": r.credits_drawn,
        }
        stmt = pg_insert(SubscriptionUsageDaily).values(**values)
        table = SubscriptionUsageDaily.__table__
        additive = {k: table.c[k] + stmt.excluded[k] for k in values if k not in {"day", "provider", "model", "project", "speed"}}
        await db.execute(stmt.on_conflict_do_update(index_elements=["day", "provider", "model", "project", "speed"], set_=additive))
    for ev in snapshots:
        await db.execute(
            pg_insert(SubscriptionUsageSnapshot)
            .values(provider=ev.provider, observed_at=ev.ts, window_minutes=ev.window_minutes,
                    used_percent=ev.used_percent, resets_at=ev.resets_at, plan_type=ev.plan_type,
                    credits_balance=ev.credits_balance)
            .on_conflict_do_nothing(constraint="uq_subscription_usage_snapshot")
        )
    for ts, credits in new_lots:
        db.add(CreditLot(provider="codex", source="unclassified", credits=credits, granted_at=ts,
                         evidence="Detected balance increase; classify as grant or purchase (paid_usd)."))
    for path, (offset, state) in result.cursors.items():
        stmt = pg_insert(SubscriptionUsageCursor).values(path=path, offset=offset, state=state)
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["path"],
            set_={"offset": stmt.excluded.offset, "state": stmt.excluded.state, "updated_at": func.now()},
        ))
    cutoff = datetime.now(UTC) - timedelta(days=CURSOR_RETAIN_DAYS)
    await db.execute(
        delete(SubscriptionUsageCursor).where(
            SubscriptionUsageCursor.updated_at < cutoff, ~SubscriptionUsageCursor.path.startswith("@")
        )
    )
