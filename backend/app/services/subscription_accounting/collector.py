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
# Runaway backstop: one transcript file is one session or subagent. The auto-compact settings keep
# turns near 200K; a turn this big means compaction isn't holding, and this much value in a single
# run means an agent is looping on a huge history. Each file alerts once per signal.
RUNAWAY_TURN_CONTEXT = 400_000
RUNAWAY_RUN_USD = 75.0
# Per-call ledger (usage_calls). A cursor without this version is re-read from the start once so its
# history lands in the ledger; lines before the old offset feed only the ledger (rollups already have them).
# A replay also prices calls stored without a rate whose model has since gained one in the catalog,
# and names review runs (v4) whose sub-agents were showing as separate rows.
LEDGER_VERSION = 4
COLLECT_LOCK_KEY = 0x55A6E_C011  # one pass at a time across the API and the timer
PASS_BYTE_BUDGET = 1_000_000_000  # replay bytes per pass; live files are always read first
CODEX_ROUTINE_ORIGINATORS = frozenset({"codex_exec"})
CODEX_INTERACTIVE_ORIGINATORS = frozenset({"codex-tui", "codex_cli_rs", "codex_work_desktop", "codex_vscode"})
_ORDINAL = re.compile(rb'"ordinal":(\d+)')
_JOB_MASK = re.compile(r"\b(?:[0-9a-f]{7,}|[0-9a-f-]{20,}|task-[0-9a-z]+|\d[\d:.\-/]*)\b", re.IGNORECASE)
_SCAFFOLD_PREFIXES = (
    "# AGENTS", "<", "Message Type", "The following is the Codex agent history", "Caveat:", "[Request interrupted",
)


def claude_statusline_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "claude-usage" / "rate-limits.json"


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


@dataclass
class PassResult:
    rollups: dict[tuple[date, str, str, str, str], Rollup] = field(default_factory=lambda: defaultdict(Rollup))
    cursors: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)
    balances: list[BalanceEvent] = field(default_factory=list)
    snapshots: list[SnapshotEvent] = field(default_factory=list)
    files_read: int = 0
    bytes_read: int = 0
    runaways: list[str] = field(default_factory=list)
    calls: list[UsageCallRow] = field(default_factory=list)
    sessions: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    replay_pending: int = 0


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
    result.calls.append(call)
    _put_session(result, provider, state, call.occurred_at)


# ------------------------------------------------------------------ Codex


def _track_run(result: PassResult, path: Path, state: dict[str, Any], ts: datetime, context: int, usd: float) -> None:
    """Per-transcript peak turn context and cumulative value; queue one alert per signal."""
    state["max_ctx"] = max(int(state.get("max_ctx") or 0), context)
    state["usd"] = float(state.get("usd") or 0.0) + usd
    state["turns"] = int(state.get("turns") or 0) + 1
    alerted: list[str] = state.setdefault("alerted", [])
    for signal, hit, note in (
        ("ctx", state["max_ctx"] >= RUNAWAY_TURN_CONTEXT, f"a single turn read {state['max_ctx'] // 1000}K tokens of context"),
        ("usd", state["usd"] >= RUNAWAY_RUN_USD, f"one run is at ${state['usd']:.0f} API-equivalent"),
    ):
        if hit and signal not in alerted:
            alerted.append(signal)
            if datetime.now(UTC) - ts > timedelta(hours=2):
                continue  # backfilled history: remember it, don't page for it
            who = "subagent" if any(part.startswith("subagent") for part in path.parts) else "session"
            result.runaways.append(f"A {who} transcript ({path.stem[:24]}) looks runaway: {note} after {state['turns']} turns.")


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
        if b'"token_count"' not in head:
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
            call = _codex_call(path, state, ts, model, speed, last, total)
            _add_call(result, call, state, "codex")
            if live:
                _add_codex_rollup(result, call, project, speed)
                _track_run(result, path, state, ts, call.input_tokens + call.cached_input_tokens,
                           call.api_equiv_usd or 0.0)
        if live:
            _codex_rate_limits(result, ts, model, project, speed, payload.get("rate_limits") or {})
    _register_codex_root(result, state)
    return offset


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
    seen: list[str] = state.setdefault("seen", [])
    seen_set = set(seen)
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
        if ident in seen_set:
            continue
        seen.append(ident)
        seen_set.add(ident)
        entry = rec.get("entrypoint")
        if isinstance(entry, str) and entry and "kind" not in state:
            state["kind"] = "interactive" if entry == "cli" else "routine" if entry.startswith("sdk") else "other"
        if not state.get("project"):
            state["project"] = project_from_cwd(rec.get("cwd"))
        usage = msg["usage"]
        call, speed, project = _claude_call(state, ts, model, ident, usage, rec)
        _add_call(result, call, state, "claude")
        if end > live_from:
            _add_claude_rollup(result, call, project, speed)
            context = call.input_tokens + call.cached_input_tokens + call.cache_write_tokens
            _track_run(result, path, state, ts, context, call.api_equiv_usd or 0.0)
    del seen[:-MAX_SEEN_IDS]
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


def scan(
    cursors: dict[str, tuple[int, dict[str, Any]]], now: float | None = None, byte_budget: int = PASS_BYTE_BUDGET
) -> PassResult:
    """Read new log bytes (blocking; run in a thread). cursors: path -> (offset, state).

    Files whose cursor predates the call ledger are replayed from the start (ledger only for the bytes
    already counted), newest first, within byte_budget per pass; live appends are always read first.
    """
    now = now or time.time()
    since = now - BACKFILL_DAYS * 86400
    result = PassResult()
    jobs = [(p, _codex_file) for root in codex_session_roots() for p in _candidate_files(root, "*/*/*/*.jsonl", since)]
    jobs += [(p, _claude_file) for root in claude_project_roots() for p in _candidate_files(root, "**/*.jsonl", since)]
    live: list[tuple[Path, Any, int, dict[str, Any], int]] = []
    replay: list[tuple[float, Path, Any, int, dict[str, Any]]] = []
    for path, reader in jobs:
        offset, state = cursors.get(str(path), (0, {}))
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size < offset:
            offset, state = 0, {}
        if offset and state.get("ledger") != LEDGER_VERSION:
            replay.append((stat.st_mtime, path, reader, offset, dict(state)))
        elif stat.st_size != offset:
            live.append((path, reader, offset, dict(state), 0))
    replay.sort(key=lambda item: item[0], reverse=True)
    spent = 0
    for _mtime, path, reader, offset, old in replay:
        if spent >= byte_budget:
            result.replay_pending += 1
            continue
        fresh = {k: old[k] for k in ("max_ctx", "usd", "turns", "alerted") if k in old}
        live.append((path, reader, 0, fresh, offset))
        spent += offset
    for path, reader, offset, state, live_from in live:
        state["ledger"] = LEDGER_VERSION
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


async def collect(db: AsyncSession, *, min_interval_s: float = 300.0) -> dict[str, Any]:
    """Run one incremental pass unless one ran within min_interval_s. Commits its own transaction."""
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
        for message in result.runaways:
            await _alert(message)
        return {"files_read": result.files_read, "bytes_read": result.bytes_read, "snapshots": len(snapshots),
                "new_lots": len(new_lots), "calls": len(result.calls), "replay_pending": result.replay_pending}


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
    await _persist_ledger(db, result)
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
    for i in range(0, len(result.calls), LEDGER_CHUNK):
        rows = [
            {"call_key": c.key, "occurred_at": c.occurred_at, "provider": c.provider, "session_id": c.session_id[:100],
             "agent_id": c.agent_id[:100], "model": c.model[:100], "input_tokens": c.input_tokens,
             "cached_input_tokens": c.cached_input_tokens, "cache_write_tokens": c.cache_write_tokens,
             "output_tokens": c.output_tokens, "api_equiv_usd": c.api_equiv_usd}
            for c in result.calls[i:i + LEDGER_CHUNK]
        ]
        stmt = pg_insert(UsageCall).values(rows)
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["call_key"], set_={"api_equiv_usd": stmt.excluded.api_equiv_usd},
            where=UsageCall.api_equiv_usd.is_(None),
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
    message: str, *, title: str = "Agent context runaway", key: str | None = None, cooldown: int = 0,
    open_url: str | None = None,
) -> None:
    """Owner alert through Nightshift's push (the only owner-alert path)."""
    binary = shutil.which("nightshift")
    if binary is None:
        logger.warning("nightshift not found; alert not sent: %s", message)
        return
    args = ["push", "--severity", "warning", "--title", title, "--key", key or f"runaway:{message[:60]}",
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
