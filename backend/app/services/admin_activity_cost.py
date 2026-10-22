"""Bounded, content-free activity observations for the existing admin hotspot view.

Tools establish observed activity, not the purpose of every token in a turn.
Independent accounting sources are alternatives, never additive for a session.
"""

from __future__ import annotations

import shlex
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session, SessionBinding, SessionEvent, UsageCall

EVENT_LIMIT = 20_000
CATEGORIES = ("substantive", "necessary_support", "administration", "mixed", "unknown")
_ADMIN = {"context", "task", "show", "list", "ready", "ready-all", "claim", "done", "log", "plan", "portfolio", "session", "sessions", "agent", "hub", "prompt", "memory", "lease", "queue", "ownership", "batch"}
_SUPPORT = {"check", "commit", "service", "services", "build", "deploy"}


def _combined(categories: set[str]) -> str:
    categories = {"administration" if category == "necessary_support" else category for category in categories}
    return next(iter(categories)) if len(categories) == 1 else "mixed" if categories else "unknown"


def _command_family(words: list[str]) -> tuple[str, str]:
    if not words:
        return "unknown", "unknown"
    executable = PurePosixPath(words[0]).name
    if executable in {"bash", "sh", "zsh"} and len(words) == 3 and words[1] in {"-c", "-lc"}:
        return _shell_family(words[2])
    if executable == "st":
        args = words[1:]
        while len(args) >= 2 and args[0] in {"-P", "--project"}:
            args = args[2:]
        verb = args[0] if args else ""
        if verb in _ADMIN:
            return f"st.{verb}", "administration"
        if verb in _SUPPORT:
            return f"st.{verb}", "necessary_support"
    if executable in {"git", "docker", "systemctl", "pytest", "ruff", "npm", "pnpm", "uv"}:
        # Package runners can invoke arbitrary programs; only known check/build operations qualify.
        if executable in {"npm", "pnpm", "uv"} and not any(word in {"test", "build", "lint", "check", "sync"} for word in words[1:3]):
            return "unknown", "unknown"
        return executable, "necessary_support"
    if executable in {"sleep", "wait"}:
        return "explicit_wait", "wait"
    return "unknown", "unknown"


def _shell_family(command: str) -> tuple[str, str]:
    # No execution, expansion, or parsing of scripts. Unsupported syntax remains unknown.
    if any(token in command for token in ("$", "`", "<<", "(", ")")):
        return "unknown", "unknown"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace = " \t\r"
        words = list(lexer)
    except ValueError:
        return "unknown", "unknown"
    segments: list[list[str]] = [[]]
    for word in words:
        if word and all(character in ";&|\n" for character in word):
            segments.append([])
        else:
            segments[-1].append(word)
    observations = [_command_family(segment) for segment in segments if segment]
    families = {family for family, _ in observations}
    categories = {category for _, category in observations}
    # A compound call has no per-command duration. Its category can be mixed.
    return (next(iter(families)) if len(families) == 1 else "compound"), _combined(categories)


def _tool_family(event: Any) -> tuple[str, str]:
    tool = (event.tool_name or "").split(".")[-1].lower()
    data = event.tool_input if isinstance(event.tool_input, dict) else {}
    if tool in {"bash", "exec_command", "run_command"}:
        command = data.get("command", data.get("cmd"))
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            return _command_family(command)
        return _shell_family(command) if isinstance(command, str) else ("unknown", "unknown")
    if tool in {"apply_patch", "write_file", "edit_file", "write", "edit"}:
        return "editing", "substantive"
    if tool in {"web__run", "web_search", "web_research", "web_fetch", "search_web"}:
        return "web_research", "substantive"
    if tool in {"sleep", "wait", "wait_agent"} or (tool == "write_stdin" and not data.get("chars")):
        return "explicit_wait", "wait"
    return "unknown", "unknown"


def _number(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _token_view(counts: dict[str, int], sources: list[dict] | None = None) -> dict:
    total = sum(counts.values())
    coarse = {"substantive": counts["substantive"], "administration": counts["administration"] + counts["necessary_support"], "unknown": counts["unknown"] + counts["mixed"]}
    return {
        "denominator": total,
        "unclassified_share": (counts["mixed"] + counts["unknown"]) / total if total else None,
        "mixed_tokens": counts["mixed"],
        "breakdown": [{"category": category, "tokens": amount, "share": amount / total if total else None} for category, amount in coarse.items()],
        "sources": sources or [],
    }


def _occupancy(intervals: list[tuple[datetime, datetime, str]]) -> dict[str, float]:
    """Union per-session intervals; concurrent different categories stay mixed."""
    boundaries: dict[datetime, list[tuple[str, int]]] = defaultdict(list)
    for start, end, category in intervals:
        if end > start:
            boundaries[start].append((category, 1))
            boundaries[end].append((category, -1))
    active: dict[str, int] = defaultdict(int)
    seconds: dict[str, float] = defaultdict(float)
    previous = None
    for timestamp, changes in sorted(boundaries.items()):
        categories = {category for category, count in active.items() if count > 0 and category != "wait"}
        category = _combined(categories) if categories else "wait" if active.get("wait", 0) > 0 else None
        if previous is not None and category is not None:
            seconds[category] += (timestamp - previous).total_seconds()
        for name, delta in changes:
            active[name] += delta
        previous = timestamp
    return seconds


def _time_view(seconds: dict[str, float]) -> dict:
    total = sum(seconds.get(category, 0) for category in CATEGORIES)
    coarse = {"substantive": seconds.get("substantive", 0), "administration": seconds.get("administration", 0) + seconds.get("necessary_support", 0), "unknown": seconds.get("unknown", 0) + seconds.get("mixed", 0)}
    return {
        "basis": "Union of reported tool-runtime intervals per session; concurrent sessions add. Intervals end at source timestamp when available, otherwise stored event timestamp (approximate placement). Explicit wait-only time is excluded. This is observed tool occupancy, not total agent thinking or active time.",
        "denominator_seconds": round(total, 3),
        "explicit_wait_seconds": round(seconds.get("wait", 0), 3),
        "mixed_seconds": round(seconds.get("mixed", 0), 3),
        "thinking_seconds": None,
        "idle_seconds": None,
        "breakdown": [{"category": category, "seconds": round(amount, 3), "share": amount / total if total else None} for category, amount in coarse.items()],
    }


def summarize_activity_cost(
    events: list[Any], cost_rows: list[Any], usage_rows: list[Any], sessions: list[Any], bindings: list[Any],
    *, cutoff: datetime, now: datetime, limit: int, truncated: bool,
) -> dict[str, Any]:
    """Combine only source-backed identities; return no prompts, commands, or tool outputs."""
    by_session = {session.id: session for session in sessions}
    events = sorted(events, key=lambda event: (event.session_id, event.turn, event.sequence))
    suppressed = {
        (event.session_id, event.tool_input["wrapper_candidate_call_id"])
        for event in events if event.event_type == "tool_use" and isinstance(event.tool_input, dict)
        and event.tool_input.get("wrapper_correlation") == "nested_command_digest"
        and isinstance(event.tool_input.get("wrapper_candidate_call_id"), str)
    }
    tools: dict[tuple[str, str], Any] = {}
    results: dict[tuple[str, str], Any] = {}
    for event in events:
        if (event.session_id, event.call_id) not in suppressed:
            key = (event.session_id, event.call_id or str(event.id))
            if event.event_type == "tool_use":
                tools.setdefault(key, event)
            elif event.event_type == "tool_result":
                results[key] = event
    # A result whose use fell outside the window still measures occupancy, but
    # cannot establish command purpose. Do not guess a neighboring tool match.
    for key, result in results.items():
        if key not in tools:
            tools[key] = result

    turn_categories: dict[tuple[str, int], set[str]] = defaultdict(set)
    intervals: dict[str, list] = defaultdict(list)
    patterns: dict[str, dict] = {}
    missing_duration = 0
    for key, tool in tools.items():
        family, category = _tool_family(tool)
        turn_categories[(tool.session_id, tool.turn)].add("unknown" if category == "wait" else category)
        result = results.get(key)
        seconds = _number(result.duration_ms if result is not None else tool.duration_ms) / 1000
        end_event = result or tool
        timestamp = end_event.source_timestamp or end_event.created_at
        measured = seconds > 0 and isinstance(timestamp, datetime)
        if measured:
            end = min(timestamp.astimezone(UTC), now)
            start = max(timestamp.astimezone(UTC) - timedelta(seconds=seconds), cutoff)
            intervals[tool.session_id].append((start, end, category))
        else:
            missing_duration += 1
        if category in {"administration", "necessary_support"}:
            pattern = patterns.setdefault(family, {"family": family, "category": "administration", "calls": 0, "session_ids": set(), "intervals": defaultdict(list)})
            pattern["calls"] += 1
            pattern["session_ids"].add(tool.session_id)
            if measured:
                pattern["intervals"][tool.session_id].append((start, end, category))

    response_counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(CATEGORIES, 0))
    seen_responses: set[tuple[str, str]] = set()
    native_ids: dict[tuple[str, int], set[str]] = defaultdict(set)
    for event in events:
        usage = event.usage if isinstance(event.usage, dict) else {}
        if usage.get("scope") == "response" and isinstance(usage.get("turn_id"), str):
            native_ids[(event.session_id, event.turn)].add(usage["turn_id"])
    for event in events:
        usage = event.usage if isinstance(event.usage, dict) else {}
        if event.event_type != "usage" or usage.get("scope") != "response":
            continue
        if any(not isinstance(usage.get(field), int) or isinstance(usage[field], bool) or usage[field] < 0 for field in ("input_tokens", "output_tokens")):
            continue
        identity = usage.get("response_id")
        if not isinstance(identity, str) or not identity:
            # Without a response identity, duplicate/cumulative accounting cannot be ruled out.
            continue
        key = (event.session_id, identity)
        if key in seen_responses:
            continue
        seen_responses.add(key)
        category = _combined(turn_categories[(event.session_id, event.turn)])
        if len(native_ids[(event.session_id, event.turn)]) > 1:
            category = "mixed"
        if truncated:
            category = "unknown"
        response_counts[event.session_id][category] += _number(usage.get("input_tokens")) + _number(usage.get("output_tokens"))

    costs = {row.session_id: row for row in cost_rows}
    ledger = {row.session_id: row for row in usage_rows if row.session_id is not None}
    tokens = dict.fromkeys(CATEGORIES, 0)
    responses = dict.fromkeys(CATEGORIES, 0)
    seconds: dict[str, float] = defaultdict(float)
    token_sources: dict[str, dict] = {}
    per_session: dict[str, dict] = {}
    overlaps = missing_usage = 0
    for sid in by_session:
        observed = response_counts.get(sid, dict.fromkeys(CATEGORIES, 0))
        for category in CATEGORIES:
            responses[category] += observed[category]
        available = [name for name, present in (("cost_logs", sid in costs), ("usage_calls", sid in ledger), ("response_events", sid in response_counts)) if present]
        source = available[0] if available else "missing"
        overlaps += max(len(available) - 1, 0)
        counts = dict.fromkeys(CATEGORIES, 0)
        if source in {"cost_logs", "usage_calls"}:
            row = costs[sid] if source == "cost_logs" else ledger[sid]
            counts["unknown"] = _number(row.input_tokens) + _number(row.output_tokens)
        elif source == "response_events":
            counts = observed
        else:
            missing_usage += 1
        amount = sum(counts.values())
        coverage = token_sources.setdefault(source, {"source": source, "sessions": 0, "tokens": 0})
        coverage["sessions"] += 1
        coverage["tokens"] += amount
        occupancy = _occupancy(intervals[sid])
        per_session[sid] = {"counts": counts, "seconds": occupancy}
        for category in CATEGORIES:
            tokens[category] += counts[category]
        for category, duration in occupancy.items():
            seconds[category] += duration

    task_links: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for binding in bindings:
        session = by_session.get(binding.session_id)
        if session is not None and binding.task_id and binding.project_id == session.project_id:
            task_links[binding.session_id].add((binding.project_id, binding.task_id))
    tasks: dict[tuple[str, str], dict] = {}
    unlinked = unlinked_tokens = 0
    unlinked_tool_seconds = 0.0
    for sid, metrics in per_session.items():
        links = task_links[sid]
        if len(links) != 1:
            unlinked += 1
            unlinked_tokens += sum(metrics["counts"].values())
            unlinked_tool_seconds += sum(metrics["seconds"].get(category, 0) for category in CATEGORIES)
            continue
        project, task = next(iter(links))
        row = tasks.setdefault((project, task), {"project_id": project, "task_id": task, "sessions": 0, "tokens": 0, "counts": dict.fromkeys(CATEGORIES, 0), "seconds": defaultdict(float)})
        row["sessions"] += 1
        row["tokens"] += sum(metrics["counts"].values())
        for category, amount in metrics["counts"].items():
            row["counts"][category] += amount
        for category, amount in metrics["seconds"].items():
            row["seconds"][category] += amount

    repeats = [{"family": family, "category": row["category"], "calls": row["calls"], "sessions": len(row["session_ids"]), "measured_tool_seconds": round(sum(sum(_occupancy(spans).values()) for spans in row["intervals"].values()), 3), "avoidable": None} for family, row in patterns.items() if row["calls"] > 1]
    repeats.sort(key=lambda row: (row["measured_tool_seconds"], row["calls"]), reverse=True)
    task_rows = [{"project_id": row["project_id"], "task_id": row["task_id"], "sessions": row["sessions"], "tokens": row["tokens"], "token_breakdown": _token_view(row["counts"])["breakdown"], "tool_time": _time_view(row["seconds"])} for row in tasks.values()]
    task_rows.sort(key=lambda row: (row["tokens"], row["tool_time"]["denominator_seconds"]), reverse=True)
    tool_time = _time_view(seconds)
    shares = {row["category"]: row["share"] for row in tool_time["breakdown"]}
    summary = "No measured tool-runtime intervals in this window."
    if tool_time["denominator_seconds"]:
        summary = f"Of {tool_time['denominator_seconds']:g} measured active tool seconds: {shares['substantive']:.0%} substantive, {shares['administration']:.0%} administration including support, {shares['unknown']:.0%} unknown including mixed. Thinking and idle time are unmeasured."
    return {
        "scope": "All Hub sessions created/updated or with observed events/accounting in the window, across providers. Sessions without usage remain visible.",
        "window_start": cutoff.isoformat(), "window_end": now.isoformat(),
        "sessions": len(by_session), "events_sampled": len(events), "event_limit": EVENT_LIMIT,
        "events_truncated": truncated, "missing_usage_sessions": missing_usage,
        "unlinked_sessions": unlinked, "overlapping_sources_excluded": overlaps,
        "unlinked_tokens": unlinked_tokens, "unlinked_tool_seconds": round(unlinked_tool_seconds, 3),
        "tokens": _token_view(tokens, list(token_sources.values())),
        "token_basis": "One source per session, in order: cost_logs, matched usage_calls, response events. Ledger tokens remain unknown without a stable turn/response join. Ledger input adds disjoint cache-read/write tokens; native response input already includes cache and output includes reasoning.",
        "response_tokens": _token_view(responses),
        "response_token_basis": "Separate overlapping evidence, never added to the primary denominator: unique response IDs, scope=response, input+output (Codex input includes cache; output includes reasoning). Category describes all observed tools in the normalized user turn, not exact per-command cost or the intent of every token.",
        "tool_time": tool_time, "tools_missing_duration": missing_duration,
        "summary": summary, "repeat_admin_patterns": repeats[:limit],
        "task_rollups": task_rows[:limit], "task_rollups_total": len(task_rows),
        "limits": [
            "Tool categories are conservative observations; unsupported commands and unseen work stay unknown. Mixed turns are not split into invented token allocations.",
            "Repeated administration is not evidence that it was unnecessary. Avoidable ceremony is unknown.",
            "Source precedence prevents double counting, but partial/disjoint source histories can be omitted. This is a recorded-token coverage view, not a reconciled billing total.",
            "The event sample can omit tool/response associations; truncation makes response attribution unknown. Missing usage and tool duration have unknown size; token shares cover recorded tokens only. Family time can overlap other families.",
            "Explicit waits are observed wait-only tool occupancy, not all waiting. Native turn wall spans include thinking and waits; neither elapsed time nor tool occupancy measures total active thinking time.",
            "Task linkage uses only one unambiguous project/task session binding. External IDs and inferred task names are not task evidence.",
        ],
    }


async def build_activity_cost_snapshot(db: AsyncSession, *, cutoff: datetime, now: datetime, limit: int) -> dict[str, Any]:
    """Bound event memory, aggregate ledgers in SQL, and include old-but-active sessions."""
    event_time = func.coalesce(SessionEvent.source_timestamp, SessionEvent.created_at)
    events = (await db.execute(select(
        SessionEvent.id, SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence,
        SessionEvent.event_type, SessionEvent.call_id, SessionEvent.tool_name, SessionEvent.tool_input,
        SessionEvent.usage, SessionEvent.duration_ms, SessionEvent.source_timestamp, SessionEvent.created_at,
    ).where(event_time >= cutoff, event_time <= now, SessionEvent.event_type.in_(["tool_use", "tool_result", "usage"]))
        .order_by(event_time.desc(), SessionEvent.id).limit(EVENT_LIMIT + 1))).all()
    cost_rows = (await db.execute(select(
        CostLog.session_id, func.sum(CostLog.input_tokens + CostLog.cache_read_tokens + CostLog.cache_write_tokens).label("input_tokens"),
        func.sum(CostLog.output_tokens).label("output_tokens"), func.count().label("calls"),
    ).where(CostLog.created_at >= cutoff, CostLog.created_at <= now).group_by(CostLog.session_id))).all()
    # Collector root/agent identity is explicit. A root's child usage must never also count in its root.
    native_id = case((UsageCall.agent_id != "", UsageCall.agent_id), else_=UsageCall.session_id)
    # Claude hooks historically registered anthropic, or openai with the
    # claude_code session type. Keep exact identity and known native semantics.
    native_provider = case(
        (Session.provider == "codex", "codex"),
        (Session.provider.in_(["claude", "anthropic"]), "claude"),
        ((Session.provider == "openai") & (Session.session_type == "claude_code"), "claude"),
        else_=Session.provider,
    )
    usage_rows = (await db.execute(select(
        Session.id.label("session_id"),
        func.sum(UsageCall.input_tokens + UsageCall.cached_input_tokens + UsageCall.cache_write_tokens).label("input_tokens"),
        func.sum(UsageCall.output_tokens).label("output_tokens"), func.count().label("calls"),
    ).select_from(UsageCall).join(Session, (Session.id == native_id) & (native_provider == UsageCall.provider))
        .where(UsageCall.occurred_at >= cutoff, UsageCall.occurred_at <= now).group_by(Session.id))).all()
    ids = {row.session_id for row in [*events[:EVENT_LIMIT], *cost_rows, *usage_rows]}
    sessions = (await db.execute(select(Session.id, Session.project_id, Session.provider).where(or_(
        Session.id.in_(ids), Session.created_at.between(cutoff, now), Session.updated_at.between(cutoff, now),
    )))).all()
    ids = {session.id for session in sessions}
    bindings = (await db.execute(select(SessionBinding.session_id, SessionBinding.project_id, SessionBinding.task_id)
        .where(SessionBinding.session_id.in_(ids), SessionBinding.task_id.is_not(None)))).all() if ids else []
    return summarize_activity_cost(events[:EVENT_LIMIT], cost_rows, usage_rows, sessions, bindings,
        cutoff=cutoff, now=now, limit=limit, truncated=len(events) > EVENT_LIMIT)
