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
import re
import shutil
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CreditLot,
    SubscriptionUsageCursor,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
    UsageCall,
    UsageSession,
)
from app.utils.native_homes import claude_project_roots, codex_session_roots, native_homes
from app.utils.safe_subprocess import create_process

from . import rates

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 40
CURSOR_RETAIN_DAYS = 45
LEDGER_RETAIN_DAYS = 120
LOT_MIN_CREDITS = 1000.0
SNAPSHOT_MIN_INTERVAL_S = 15 * 60
MAX_SEEN_IDS = 500
CODEX_CREDIT_STATE = "@codex_credits"
SNAPSHOT_STATE = "@snapshots"
CLAUDE_STATUSLINE_STATE = "@claude_statusline"
CLAUDE_WINDOWS = {"five_hour": 300, "seven_day": 10080}
# Per-call ledger (usage_calls). A cursor without this version is re-read from the start once so its
# history lands in the ledger; lines before the old offset feed only the ledger (rollups already have them).
# A replay also prices calls stored without a rate whose model has since gained one in the catalog,
# and names review runs (v4) whose sub-agents were showing as separate rows.
LEDGER_VERSION = 4
COLLECT_LOCK_KEY = 0x55A6E_C011  # one pass at a time across the API and the timer
PASS_BYTE_BUDGET = 1_000_000_000  # replay bytes per pass; live files are always read first
CODEX_ROUTINE_ORIGINATORS = frozenset({"codex_exec"})
CODEX_INTERACTIVE_ORIGINATORS = frozenset({"codex-tui", "codex_cli_rs", "codex_work_desktop", "codex_vscode"})
_ORDINAL = re.compile(rb'"ordinal":\s*(\d+)')
_JOB_MASK = re.compile(r"\b(?:[0-9a-f]{7,}|[0-9a-f-]{20,}|task-[0-9a-z]+|\d[\d:.\-/]*)\b", re.IGNORECASE)
_SCAFFOLD_PREFIXES = (
    "# AGENTS", "<", "Message Type", "The following is the Codex agent history", "Caveat:", "[Request interrupted",
)


def claude_statusline_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "claude-usage" / "rate-limits.json"


def claude_statusline_files() -> list[Path]:
    """Statusline snapshots of every user running Claude Code: this user's, then the other native homes' (the agent
    user's sits in a dir it shares with this user by ACL; a home or dir that cannot be read is skipped)."""
    own = claude_statusline_file()
    return [own, *(home / ".local" / "state" / "claude-usage" / "rate-limits.json"
                   for home in native_homes() if home != Path.home())]


def project_from_cwd(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    path = cwd.rstrip("/")
    for prefix in ("/srv/workspaces/projects/", "/srv/workspaces/", "/srv/scratch/", *(f"{home}/" for home in native_homes())):
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
class UsageCallRow:
    key: str
    occurred_at: datetime
    provider: str
    session_id: str
    agent_id: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    api_equiv_usd: float | None
    project: str = "unknown"
    speed: str = "standard"
    count_new: bool = True


@dataclass
class PassResult:
    rollups: dict[tuple[date, str, str, str, str], Rollup] = field(default_factory=lambda: defaultdict(Rollup))
    cursors: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)
    balances: list[BalanceEvent] = field(default_factory=list)
    snapshots: list[SnapshotEvent] = field(default_factory=list)
    files_read: int = 0
    bytes_read: int = 0
    calls: list[UsageCallRow] = field(default_factory=list)
    sessions: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    replay_pending: int = 0
    call_indexes: dict[str, int] = field(default_factory=dict)
    reconcile: bool = False


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


# ------------------------------------------------------------------ ledger identity


def _put_session(result: PassResult, provider: str, state: dict[str, Any], ts: datetime) -> None:
    """Record who the transcript's session (or sub-agent) is, widened to this call's time."""
    sid = state.get("sid")
    if not sid:
        return
    key = (provider, str(sid), str(state.get("aid") or ""))
    row = result.sessions.get(key)
    if row is None:
        row = result.sessions[key] = {"first_at": ts, "last_at": ts}
    row["first_at"] = min(row["first_at"], ts)
    row["last_at"] = max(row["last_at"], ts)
    row["project"] = state.get("project") or "unknown"
    row["kind"] = state.get("kind") or "other"
    row["title"] = state.get("title")
    row["job"] = (
        job_name(row["project"], state.get("title"), provider)
        if row["kind"] == "routine" and not state.get("aid") else None
    )


def job_name(project: str, title: str | None, provider: str) -> str:
    """Stable name for a routine job: its project and the start of its prompt with ids and numbers masked."""
    words = _JOB_MASK.sub("#", (title or "").strip()).split()
    sig = " ".join(words[:8])[:120] or f"{provider} run"
    return f"{project} · {sig}"[:200]


def _clean_title(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    collapsed = " ".join(text.split())
    if not collapsed or collapsed.startswith(_SCAFFOLD_PREFIXES):
        return None
    return collapsed[:300]


def _add_call(result: PassResult, call: UsageCallRow, state: dict[str, Any], provider: str) -> None:
    index = result.call_indexes.get(call.key)
    if index is None:
        result.call_indexes[call.key] = len(result.calls)
        result.calls.append(call)
    else:
        result.calls[index] = call
    _put_session(result, provider, state, call.occurred_at)


# ------------------------------------------------------------------ Codex


def _codex_meta(payload: dict[str, Any], state: dict[str, Any]) -> None:
    """Own session_meta only: copied parent headers in a child transcript never replace its identity."""
    own = payload.get("id")
    if state.get("tid") and own != state["tid"]:
        return
    state["tid"] = own
    state["cwd"] = payload.get("cwd") or state.get("cwd")
    state["project"] = project_from_cwd(state.get("cwd"))
    root = payload.get("session_id") or payload.get("parent_thread_id") or own
    state["sid"] = root
    state["aid"] = own if own and own != root else ""
    start = payload.get("subagent_history_start_ordinal")
    if isinstance(start, int) and not isinstance(start, bool):
        state["hist_start"] = start
    originator = str(payload.get("originator") or "")
    source = payload.get("source")
    if originator in CODEX_ROUTINE_ORIGINATORS:
        state["kind"] = "routine"
    elif originator in CODEX_INTERACTIVE_ORIGINATORS or source in ("cli", "vscode"):
        state["kind"] = "interactive"
    else:
        state.setdefault("kind", "other")
    sub = source.get("subagent") if isinstance(source, dict) else None
    if isinstance(sub, str):
        state["title"] = f"{sub} sub-agent"
    elif isinstance(sub, dict):
        spawn = sub.get("thread_spawn") or {}
        path = str(spawn.get("agent_path") or "").rstrip("/").rsplit("/", 1)[-1]
        state["title"] = path or spawn.get("agent_role") or spawn.get("agent_nickname") or "sub-agent"


def _codex_title(line: bytes, state: dict[str, Any]) -> None:
    with contextlib.suppress(ValueError):
        payload = json.loads(line).get("payload") or {}
        if payload.get("type") != "message" or payload.get("role") != "user":
            return
        for block in payload.get("content") or []:
            title = _clean_title(block.get("text") if isinstance(block, dict) else None)
            if title:
                state["title"] = title
                return


def _codex_review_title(line: bytes, state: dict[str, Any]) -> None:
    """`codex exec review` sends no prompt of its own; name the run after its review target."""
    with contextlib.suppress(ValueError, AttributeError):
        item = (json.loads(line).get("payload") or {}).get("item") or {}
        title = _clean_title(f"Review {item.get('user_facing_hint') or 'changes'}")
        if title:
            state["title"] = title


def _codex_file(path: Path, offset: int, state: dict[str, Any], result: PassResult, live_from: int = 0) -> int:
    """Read Codex rollout lines. Lines ending at or before live_from are a ledger replay: calls only."""
    for end, line in _iter_new_lines(path, offset):
        offset = end
        live = end > live_from
        head = line[:400]
        if b'"session_meta"' in head:
            with contextlib.suppress(ValueError):
                rec = json.loads(line)
                _codex_meta(rec.get("payload") or {}, state)
                state.setdefault("meta_ts", rec.get("timestamp"))
            continue
        if not state.get("title") and b'"response_item"' in head and b'"role":"user"' in head:
            _codex_title(line, state)
            continue
        if not state.get("title") and b'"EnteredReviewMode"' in head:
            _codex_review_title(line, state)
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
        if not any(kind in head for kind in (b'"token_count"', b'"token_usage_record"', b'"compacted"')):
            continue
        hist_start = state.get("hist_start")
        ordinal = _ORDINAL.search(head) if hist_start is not None else None
        if ordinal and hist_start is not None and int(ordinal.group(1)) < hist_start:
            continue  # inherited parent history: counted in the parent's own transcript
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        payload = rec.get("payload") or {}
        if rec.get("type") == "token_usage_record" or payload.get("type") == "token_usage_record":
            if payload.get("thread_id") and state.get("tid") and payload["thread_id"] != state["tid"]:
                continue
            response = payload.get("response_id")
            if response and response not in state.get("responses", []):
                state["pending_usage"] = {
                    "response": response, "usage": payload.get("usage") or {}, "timestamp": rec.get("timestamp"),
                    "model": payload.get("model") or state.get("model"), "speed": state.get("speed"),
                    "live": live,
                }
            continue
        if rec.get("type") == "compacted":
            pending = state.get("pending_usage")
            if pending and pending["response"] == payload.get("compaction_response_id"):
                pending["live"] = pending["live"] or live
                _codex_native_call(path, state, result, pending, pending["response"])
                state.pop("pending_usage", None)
            continue
        ts = _parse_ts(rec.get("timestamp"))
        if payload.get("type") != "token_count" or ts is None:
            continue
        model = str(state.get("model") or "unknown")
        project = project_from_cwd(state.get("cwd"))
        speed = str(state.get("speed") or "standard")
        info = payload.get("info") or {}
        total = (info.get("total_token_usage") or {}).get("total_tokens")
        last = info.get("last_token_usage") or {}
        pending = state.pop("pending_usage", None)
        positive = any(int(last.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        if pending and positive:
            pending["live"] = pending["live"] or live
            _codex_native_call(path, state, result, pending, total)
            state["last_total"] = total
        elif pending:
            _codex_native_call(path, state, result, pending, pending["response"])
        elif positive and total != state.get("last_total"):
            state["last_total"] = total
            call = _codex_call(path, state, ts, model, speed, last, total)
            call.count_new = live
            _add_call(result, call, state, "codex")
            if live:
                _add_codex_rollup(result, call, project, speed)
        if live:
            _codex_rate_limits(result, ts, model, project, speed, payload.get("rate_limits") or {})
    _register_codex_root(result, state)
    return offset


def _codex_native_call(path: Path, state: dict[str, Any], result: PassResult, pending: dict, identity: object) -> None:
    ts = _parse_ts(pending.get("timestamp"))
    if ts is None:
        return
    response = pending["response"]
    responses = state.setdefault("responses", [])
    if response in responses:
        return
    responses.append(response)
    del responses[:-MAX_SEEN_IDS]
    speed = pending.get("speed") or "standard"
    call = _codex_call(path, state, ts, pending.get("model") or "unknown", speed, pending["usage"], identity)
    # Ordinary pairs keep the old cumulative key. Only the compaction response had no
    # counterpart in historical daily totals, so explicit replay may add that missing call.
    call.count_new = pending["live"] or (result.reconcile and identity == response)
    _add_call(result, call, state, "codex")
    if pending["live"]:
        _add_codex_rollup(result, call, call.project, speed)


def _register_codex_root(result: PassResult, state: dict[str, Any]) -> None:
    """A review parent can spend nothing itself; record its identity so its sub-agents roll up to its job."""
    if state.get("root_known") or state.get("aid") or not state.get("sid") or not state.get("title"):
        return
    ts = _parse_ts(state.get("meta_ts"))
    if ts is not None:
        _put_session(result, "codex", state, ts)
        state["root_known"] = True


def _codex_call(
    path: Path, state: dict[str, Any], ts: datetime, model: str, speed: str, last: dict, total: object
) -> UsageCallRow:
    total_in = int(last.get("input_tokens") or 0)
    cached = int(last.get("cached_input_tokens") or 0)
    uncached = max(total_in - cached, 0)
    out = int(last.get("output_tokens") or 0)
    credits = rates.codex_credits(model, input_tokens=uncached, cached_input_tokens=cached, output_tokens=out, speed=speed)
    thread = state.get("tid") or path.stem
    return UsageCallRow(
        key=f"codex:{thread}:{total if total is not None else ts.isoformat()}"[:200],
        occurred_at=ts, provider="codex", session_id=str(state.get("sid") or thread), agent_id=str(state.get("aid") or ""),
        model=model, input_tokens=uncached, cached_input_tokens=cached, cache_write_tokens=0, output_tokens=out,
        api_equiv_usd=None if credits is None else credits * rates.CREDIT_API_PARITY_USD,
        project=project_from_cwd(state.get("cwd")), speed=speed,
    )


def _add_codex_rollup(result: PassResult, call: UsageCallRow, project: str, speed: str) -> None:
    roll = result.rollups[(_local_day(call.occurred_at), "codex", call.model, project, speed)]
    roll.requests += 1
    roll.input_tokens += call.input_tokens
    roll.cached_input_tokens += call.cached_input_tokens
    roll.output_tokens += call.output_tokens
    if call.api_equiv_usd is None:
        roll.unpriced_tokens += call.input_tokens + call.cached_input_tokens + call.output_tokens
    else:
        roll.api_equiv_usd += call.api_equiv_usd


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


def _claude_identity(path: Path, state: dict[str, Any]) -> None:
    """Main transcript <session>.jsonl, or an in-process sub-agent at <session>/subagents/agent-<id>.jsonl."""
    if state.get("sid"):
        return
    if path.parent.name == "subagents":
        state["sid"] = path.parent.parent.name
        state["aid"] = path.stem.removeprefix("agent-")
        state["title"] = _claude_agent_label(path)
    else:
        state["sid"] = path.stem
        state["aid"] = ""


def _claude_agent_label(path: Path) -> str:
    try:
        meta = json.loads(path.with_suffix(".meta.json").read_text())
    except (OSError, ValueError):
        return "sub-agent"
    label = meta.get("description") or meta.get("agentType") if isinstance(meta, dict) else None
    return _clean_title(label) or "sub-agent"


def _claude_title(rec: dict[str, Any], state: dict[str, Any]) -> None:
    if rec.get("isMeta") or rec.get("isSidechain"):
        return
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        content = next((b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"), None)
    title = _clean_title(content)
    if title:
        state["title"] = title


def _claude_file(path: Path, offset: int, state: dict[str, Any], result: PassResult, live_from: int = 0) -> int:
    """Read Claude Code transcript lines. Lines ending at or before live_from are a ledger replay: calls only."""
    _claude_identity(path, state)
    seen: dict[str, list] = state.setdefault("usage_seen", {})
    for end, line in _iter_new_lines(path, offset):
        offset = end
        if not state.get("title") and not state.get("aid") and b'"type":"user"' in line[:2000]:
            with contextlib.suppress(ValueError):
                _claude_title(json.loads(line), state)
            continue
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
        entry = rec.get("entrypoint")
        if isinstance(entry, str) and entry and "kind" not in state:
            state["kind"] = "interactive" if entry == "cli" else "routine" if entry.startswith("sdk") else "other"
        if not state.get("project"):
            state["project"] = project_from_cwd(rec.get("cwd"))
        usage = msg["usage"]
        call, speed, project = _claude_call(state, ts, model, ident, usage, rec)
        values = [call.input_tokens, call.cached_input_tokens, call.cache_write_tokens, call.output_tokens, call.api_equiv_usd]
        previous = seen.get(ident)
        if previous == values or (previous and call.output_tokens < previous[3]):
            continue
        seen[ident] = values
        call.count_new = end > live_from
        _add_call(result, call, state, "claude")
        if end > live_from:
            _add_claude_rollup(result, call, project, speed)
            if previous is not None:
                roll = result.rollups[(_local_day(ts), "claude", model, project, speed)]
                _rollup_usage(roll, previous, -1)
                roll.requests -= 1
    for ident in list(seen)[:-MAX_SEEN_IDS]:
        del seen[ident]
    return offset


def _claude_call(
    state: dict[str, Any], ts: datetime, model: str, ident: str, use: dict, rec: dict
) -> tuple[UsageCallRow, str, str]:
    inp = int(use.get("input_tokens") or 0)
    out = int(use.get("output_tokens") or 0)
    read = int(use.get("cache_read_input_tokens") or 0)
    write_total = int(use.get("cache_creation_input_tokens") or 0)
    split = use.get("cache_creation") or {}
    w5 = int(split.get("ephemeral_5m_input_tokens") or 0)
    w1h = int(split.get("ephemeral_1h_input_tokens") or 0)
    if not split:
        w1h = write_total  # Claude Code here uses the 1-hour TTL
    speed = str(use.get("speed") if use.get("speed") in rates.CLAUDE_SPEED_MULT else "standard")
    usd = rates.claude_api_equiv_usd(
        model, input_tokens=inp, output_tokens=out, cache_read=read, cache_write_5m=w5, cache_write_1h=w1h,
        speed=speed, geo=use.get("inference_geo"),
    )
    call = UsageCallRow(
        key=f"claude:{ident}"[:200], occurred_at=ts, provider="claude", session_id=str(state["sid"]),
        agent_id=str(state.get("aid") or ""), model=model, input_tokens=inp, cached_input_tokens=read,
        cache_write_tokens=w5 + w1h, output_tokens=out, api_equiv_usd=usd,
        project=project_from_cwd(rec.get("cwd")), speed=speed,
    )
    return call, speed, project_from_cwd(rec.get("cwd"))


def _add_claude_rollup(result: PassResult, call: UsageCallRow, project: str, speed: str) -> None:
    roll = result.rollups[(_local_day(call.occurred_at), "claude", call.model, project, speed)]
    roll.requests += 1
    roll.input_tokens += call.input_tokens
    roll.cached_input_tokens += call.cached_input_tokens
    roll.cache_write_tokens += call.cache_write_tokens
    roll.output_tokens += call.output_tokens
    if call.api_equiv_usd is None:
        roll.unpriced_tokens += call.input_tokens + call.output_tokens + call.cached_input_tokens + call.cache_write_tokens
    else:
        roll.api_equiv_usd += call.api_equiv_usd


def _rollup_usage(roll: Rollup, values: list, sign: int) -> None:
    inp, cached, write, out, usd = values
    roll.input_tokens += sign * inp
    roll.cached_input_tokens += sign * cached
    roll.cache_write_tokens += sign * write
    roll.output_tokens += sign * out
    if usd is None:
        roll.unpriced_tokens += sign * (inp + cached + write + out)
    else:
        roll.api_equiv_usd += sign * usd



def _claude_statusline(state: dict[str, Any], result: PassResult) -> None:
    data: dict[str, Any] = {}
    for path in claude_statusline_files():  # the newest reading wins: limits are the account's, not the user's
        try:
            got = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(got, dict) and (_epoch(got.get("observed_at")) or datetime.min.replace(tzinfo=UTC)) > (
                _epoch(data.get("observed_at")) or datetime.min.replace(tzinfo=UTC)):
            data = got
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


def scan(
    cursors: dict[str, tuple[int, dict[str, Any]]], now: float | None = None, byte_budget: int = PASS_BYTE_BUDGET,
    *, replay: str | None = None,
) -> PassResult:
    """Read new log bytes (blocking; run in a thread). cursors: path -> (offset, state).

    Files whose cursor predates the call ledger are replayed from the start (ledger only for the bytes
    already counted), newest first, within byte_budget per pass; live appends are always read first.
    An explicit replay name reconciles ledger differences into daily totals. Reuse the same name to
    resume budgeted passes; each file records completion in its existing cursor.
    """
    now = now or time.time()
    since = now - BACKFILL_DAYS * 86400
    result = PassResult(reconcile=replay is not None)
    jobs = [(p, _codex_file) for root in codex_session_roots() for p in _candidate_files(root, "*/*/*/*.jsonl", since)]
    jobs += [(p, _claude_file) for root in claude_project_roots() for p in _candidate_files(root, "**/*.jsonl", since)]
    live: list[tuple[Path, Any, int, dict[str, Any], int]] = []
    replays: list[tuple[float, Path, Any, int, dict[str, Any]]] = []
    for path, reader in jobs:
        offset, state = cursors.get(str(path), (0, {}))
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size < offset:
            offset, state = 0, {}
        if offset and (state.get("ledger") != LEDGER_VERSION or (replay and state.get("replay") != replay)):
            replays.append((stat.st_mtime, path, reader, offset, dict(state)))
        elif stat.st_size != offset:
            live.append((path, reader, offset, dict(state), 0))
    replays.sort(key=lambda item: item[0], reverse=True)
    spent = 0
    for _mtime, path, reader, offset, _old in replays:
        if spent >= byte_budget:
            result.replay_pending += 1
            continue
        live.append((path, reader, 0, {}, offset))
        spent += offset
    for path, reader, offset, state, live_from in live:
        state["ledger"] = LEDGER_VERSION
        if replay:
            state["replay"] = replay
        try:
            new_offset = reader(path, offset, state, result, live_from)
        except OSError as exc:
            logger.warning("subscription usage: cannot read %s: %s", path, exc)
            continue
        if new_offset != offset:
            result.files_read += 1
            result.bytes_read += new_offset - offset
            result.cursors[str(path)] = (new_offset, state)
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


async def collect(db: AsyncSession, *, min_interval_s: float = 300.0, replay: str | None = None) -> dict[str, Any]:
    """Run one incremental pass and commit. Named reconciliation skips retention pruning."""
    global _last_run
    if _lock.locked() or time.monotonic() - _last_run < min_interval_s:
        return {"skipped": True}
    async with _lock:
        _last_run = time.monotonic()
        locked = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": COLLECT_LOCK_KEY})).scalar()
        if not locked:
            await db.rollback()
            return {"skipped": True}
        rows = (await db.execute(select(SubscriptionUsageCursor))).scalars().all()
        cursors = {r.path: (int(r.offset), dict(r.state or {})) for r in rows}
        result = await asyncio.to_thread(scan, cursors, replay=replay)
        lots = (await db.execute(select(CreditLot).where(CreditLot.provider == "codex"))).scalars().all()
        credit_state = dict(cursors.get(CODEX_CREDIT_STATE, (0, {}))[1])
        new_lots = apply_credit_draws(result.balances, credit_state, [lot.granted_at for lot in lots], result)
        snap_state = dict(cursors.get(SNAPSHOT_STATE, (0, {}))[1])
        snapshots = select_snapshots(result.snapshots, snap_state)
        result.cursors[CODEX_CREDIT_STATE] = (0, credit_state)
        result.cursors[SNAPSHOT_STATE] = (0, snap_state)
        await _persist(db, result, snapshots, new_lots, prune=replay is None)
        await db.commit()
        return {"files_read": result.files_read, "bytes_read": result.bytes_read, "snapshots": len(snapshots),
                "new_lots": len(new_lots), "calls": len(result.calls), "replay_pending": result.replay_pending}


async def _persist(
    db: AsyncSession, result: PassResult, snapshots: list[SnapshotEvent], new_lots: list[tuple[datetime, float]],
    *, prune: bool = True,
) -> None:
    await _persist_ledger(db, result)
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
    if not prune:
        return
    ledger_cutoff = datetime.now(UTC) - timedelta(days=LEDGER_RETAIN_DAYS)
    await db.execute(delete(UsageCall).where(UsageCall.occurred_at < ledger_cutoff))
    await db.execute(delete(UsageSession).where(UsageSession.last_at < ledger_cutoff))
    cutoff = datetime.now(UTC) - timedelta(days=CURSOR_RETAIN_DAYS)
    await db.execute(
        delete(SubscriptionUsageCursor).where(
            SubscriptionUsageCursor.updated_at < cutoff, ~SubscriptionUsageCursor.path.startswith("@")
        )
    )


LEDGER_CHUNK = 2000


async def _persist_ledger(db: AsyncSession, result: PassResult) -> None:
    # Scanner totals are useful to callers before persistence. Only ledger differences may reach
    # the daily table: a retry or a corrected final usage record must not add a second request.
    for key, roll in list(result.rollups.items()):
        result.rollups[key] = Rollup(credits_drawn=roll.credits_drawn)
    for i in range(0, len(result.calls), LEDGER_CHUNK):
        calls = result.calls[i:i + LEDGER_CHUNK]
        existing = (await db.execute(
            select(UsageCall).where(UsageCall.call_key.in_([c.key for c in calls]))
            .execution_options(populate_existing=True)
        )).scalars().all()
        previous = {c.call_key: c for c in existing}
        for call in calls:
            old = previous.get(call.key)
            if old is None and not call.count_new:
                continue  # pre-ledger history was already included in the daily table
            key = (_local_day(old.occurred_at if old is not None else call.occurred_at),
                   call.provider, call.model, call.project, call.speed)
            roll = result.rollups[key]
            roll.requests += 1
            _rollup_usage(roll, [call.input_tokens, call.cached_input_tokens, call.cache_write_tokens,
                                 call.output_tokens, call.api_equiv_usd], 1)
            if old is not None:
                old_key = (_local_day(old.occurred_at), old.provider, old.model, call.project, call.speed)
                prior_roll = result.rollups[old_key]
                prior_roll.requests -= 1
                _rollup_usage(prior_roll, [old.input_tokens, old.cached_input_tokens, old.cache_write_tokens,
                                          old.output_tokens, old.api_equiv_usd], -1)
        rows = [
            {"call_key": c.key, "occurred_at": c.occurred_at, "provider": c.provider, "session_id": c.session_id[:100],
             "agent_id": c.agent_id[:100], "model": c.model[:100], "input_tokens": c.input_tokens,
             "cached_input_tokens": c.cached_input_tokens, "cache_write_tokens": c.cache_write_tokens,
             "output_tokens": c.output_tokens, "api_equiv_usd": c.api_equiv_usd}
            for c in calls
        ]
        stmt = pg_insert(UsageCall).values(rows)
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["call_key"], set_={key: stmt.excluded[key] for key in (
                "model", "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "api_equiv_usd",
            )},
        ))
    items = list(result.sessions.items())
    table = UsageSession.__table__
    for i in range(0, len(items), LEDGER_CHUNK):
        rows = [
            {"provider": p, "session_id": sid[:100], "agent_id": aid[:100], "project": (v.get("project") or "unknown")[:200],
             "kind": v.get("kind") or "other", "job": v.get("job"), "title": (v.get("title") or None) and v["title"][:300],
             "first_at": v["first_at"], "last_at": v["last_at"]}
            for (p, sid, aid), v in items[i:i + LEDGER_CHUNK]
        ]
        stmt = pg_insert(UsageSession).values(rows)
        ex = stmt.excluded
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["provider", "session_id", "agent_id"],
            set_={
                "first_at": func.least(table.c.first_at, ex.first_at),
                "last_at": func.greatest(table.c.last_at, ex.last_at),
                "kind": case((ex.kind == "other", table.c.kind), else_=ex.kind),
                "project": case((ex.project == "unknown", table.c.project), else_=ex.project),
                "title": func.coalesce(table.c.title, ex.title),
                "job": func.coalesce(ex.job, table.c.job),
            },
        ))


async def _alert(
    message: str, *, title: str, key: str | None = None, cooldown: int = 0,
    open_url: str | None = None,
) -> None:
    """Owner alert through Nightshift's push (the only owner-alert path)."""
    binary = shutil.which("nightshift")
    if binary is None:
        logger.warning("nightshift not found; alert not sent: %s", message)
        return
    args = ["push", "--severity", "warning", "--title", title, "--key", key or f"alert:{message[:60]}",
            "--cooldown", str(cooldown)]
    if open_url:
        args += ["--open", open_url]
    try:
        process = await create_process(
            binary, *args, "--", message, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=20)
    except (OSError, TimeoutError) as exc:
        logger.warning("owner alert failed: %s", exc)
