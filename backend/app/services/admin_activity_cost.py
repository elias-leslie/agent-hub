"""Bounded, content-free activity observations for the existing admin hotspot view.

Tools establish observed activity, not the purpose of every token in a turn.
Independent accounting sources are alternatives, never additive for a session.
"""

from __future__ import annotations

import asyncio
import shlex
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session, SessionBinding, SessionEvent, UsageCall
from app.services.activity_accounting import (
    argument_characters,
    returned_characters_expression,
    transcript_view,
    usage_partitions,
)
from app.services.activity_accounting import number as _number
from app.services.context_accounting import combine_context_splits, context_split, tool_context_row
from app.services.session_efficiency import duration_split, efficiency_status, session_efficiency
from app.services.session_harnesses import (
    HARNESSES,
    harness_options,
    harness_predicate,
    session_harness,
)
from app.services.session_roles import role_predicate, session_work_role, work_role_options
from app.services.st_activity import (
    POLICY,
    shell_segments,
    st_command_family,
    summarize_st_commands,
)

EVENT_LIMIT = 20_000
CATEGORIES = ("substantive", "necessary_support", "administration", "mixed", "unknown")
RESPONSE_CATEGORIES = ("investigation_only", "mixed", "support_coordination", "unknown")


def _response_action(tool: Any) -> tuple[set[str], set[str]]:
    """Recognize bounded invocation metadata; neither command success nor intent."""
    policy = POLICY["hunter_responses"]
    name = (tool.tool_name or "").split(".")[-1].lower()
    data = tool.tool_input if isinstance(tool.tool_input, dict) else {}

    def source_path(value: Any) -> bool:
        if not isinstance(value, str) or not value or value.startswith("-"):
            return False
        path = PurePosixPath(value)
        return path.suffix.lower() in policy["source_extensions"] or path.name in policy["source_directories"]

    if name in policy["source_read_tools"]:
        action = "source_read" if source_path(data.get("path", data.get("file_path"))) else None
        return ({"investigation_only"}, {action}) if action else ({"unknown"}, set())
    if name in policy["source_search_tools"]:
        action = "source_search" if source_path(data.get("path")) else None
        return ({"investigation_only"}, {action}) if action else ({"unknown"}, set())
    if name in policy["coordination_tools"]:
        return {"support_coordination"}, set()
    if name not in policy["shell_tools"]:
        _, category = _tool_family(tool)
        return {"support_coordination" if category in {"administration", "necessary_support"} else "unknown"}, set()
    command = data.get("command", data.get("cmd"))
    if isinstance(command, list) and all(isinstance(word, str) for word in command):
        commands = [command]
        if len(command) == 3 and PurePosixPath(command[0]).name in {"bash", "sh", "zsh"} and command[1] in {"-c", "-lc"}:
            commands = shell_segments(command[2])
    else:
        commands = shell_segments(command) if isinstance(command, str) else None
    categories: set[str] = set()
    actions: set[str] = set()
    for words in commands or []:
        if not words:
            continue
        executable = PurePosixPath(words[0]).name
        action = None
        bounded_read = len(words) == 2 or (len(words) == 4 and words[1] in {"-n", "-c"})
        bounded_search = len(words) == 3 or (len(words) == 4 and words[1] in {"-n", "-l", "-i", "-r", "-rn"})
        if executable in policy["source_read_commands"] and bounded_read and source_path(words[-1]):
            action = "source_read"
        elif executable in policy["source_search_commands"] and bounded_search and source_path(words[-1]):
            action = "source_search"
        elif any(words[:len(prefix)] == prefix for prefix in policy["recon_command_prefixes"]):
            action = "recon_run"
        if action:
            categories.add("investigation_only")
            actions.add(action)
        else:
            _, category = _command_family(words)
            categories.add("support_coordination" if category in {"administration", "necessary_support"} else "unknown")
    return categories or {"unknown"}, actions


def _response_usage(usage: dict) -> dict:
    """Response input is already inclusive; cache partitions never add again."""
    counts = {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
              "cache_read_tokens": 0, "cache_write_tokens": 0, "cache_detail_input_tokens": 0}
    cached, written = usage.get("cached_input_tokens"), usage.get("cache_write_tokens", 0)
    if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (cached, written)) and cached + written <= usage["input_tokens"]:
        counts.update(cache_read_tokens=cached, cache_write_tokens=written, cache_detail_input_tokens=usage["input_tokens"])
    return counts


def hunter_response_activity(events: list[Any], tools: dict, sessions: dict, *, cutoff: datetime, now: datetime, limit: int, truncated: bool) -> dict:
    """Separate response evidence; never add it to ledger totals or infer a turn join."""
    policy = POLICY["hunter_responses"]
    selected = {sid: session for sid, session in sessions.items() if session.project_id == policy["project_id"]
                and (session_work_role(session) or {}).get("id") in policy["work_roles"]}
    responses: dict[str, dict[str, dict]] = defaultdict(dict)
    duplicate_usage = unusable_usage = 0

    def timestamp(event: Any) -> datetime:
        return (event.source_timestamp or event.created_at).astimezone(UTC)

    for event in sorted(events, key=lambda event: (timestamp(event), event.sequence, str(event.id))):
        if event.session_id not in selected or event.event_type != "usage" or not cutoff <= timestamp(event) < now:
            continue
        usage = event.usage if isinstance(event.usage, dict) else {}
        if usage.get("scope") != "response":
            continue
        identity = usage.get("response_id")
        if not isinstance(identity, str) or not identity or any(
            not isinstance(usage.get(field), int) or isinstance(usage[field], bool) or usage[field] < 0
            for field in ("input_tokens", "output_tokens")
        ):
            unusable_usage += 1
            continue
        if identity in responses[event.session_id]:
            duplicate_usage += 1
            continue
        responses[event.session_id][identity] = {"at": timestamp(event), "usage": _response_usage(usage), "categories": set()}

    first_actions: dict[str, list] = defaultdict(list)
    unlinked: dict[str, int] = defaultdict(int)
    for tool in tools.values():
        if tool.session_id not in selected or tool.event_type != "tool_use" or not cutoff <= timestamp(tool) < now:
            continue
        categories, actions = _response_action(tool)
        # Pi's adapter keeps the assistant entry ID on every tool block. No
        # user-turn, timestamp proximity, call-id or purpose-based fallback.
        source = getattr(tool, "source_event_id", None)
        identity = None
        if getattr(selected[tool.session_id], "session_type", None) == "pi" and isinstance(source, str) and source.startswith("message:"):
            entry, _, index = source.removeprefix("message:").rpartition(":")
            if index.isdigit() and entry in responses[tool.session_id]:
                identity = entry
        if identity is None:
            unlinked[tool.session_id] += 1
        else:
            responses[tool.session_id][identity]["categories"].update(categories)
        for action in actions:
            first_actions[tool.session_id].append((timestamp(tool), tool.sequence, action, identity))

    def metrics(rows: list[dict]) -> dict:
        usage = {field: sum(row["usage"][field] for row in rows) for field in
                 ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens")}
        tokens = usage["input_tokens"] + usage["output_tokens"]
        breakdown = []
        for category in RESPONSE_CATEGORIES:
            matching = [row for row in rows if row["category"] == category]
            amount = sum(row["usage"]["input_tokens"] + row["usage"]["output_tokens"] for row in matching)
            breakdown.append({"category": category, "responses": len(matching),
                              "response_share": len(matching) / len(rows) if rows else None,
                              "tokens": amount, "token_share": amount / tokens if tokens else None})
        return {"responses": len(rows), "tokens": tokens, "usage": usage, "breakdown": breakdown}

    session_rows = []
    all_responses = []
    for sid, session in selected.items():
        rows = list(responses[sid].values())
        for row in rows:
            categories = row["categories"]
            row["category"] = "unknown" if truncated or not categories else next(iter(categories)) if len(categories) == 1 else "mixed"
        all_responses.extend(rows)
        first = min(first_actions[sid], key=lambda action: action[:3]) if first_actions[sid] else None
        first_identity = first[3] if first else None
        identities = list(responses[sid])
        first_response = responses[sid].get(first_identity)
        start = getattr(session, "created_at", None)
        elapsed = (first[0] - rows[0]["at"]).total_seconds() if first and rows and first[0] >= rows[0]["at"] else None
        peak = max(range(len(rows)), key=lambda index: rows[index]["usage"]["input_tokens"]) if rows else None
        session_rows.append({"session_id": sid, "project_id": session.project_id, "harness": session_harness(session),
                             "work_role": (session_work_role(session) or {})["id"], **metrics(rows),
                             "tools_without_response": unlinked[sid],
                             "window_starts_mid_session": isinstance(start, datetime) and start < cutoff,
                             "first_source_recon_signal": None if first is None else {
                                 "action": first[2], "sample_response_number": identities.index(first_identity) + 1 if first_identity in identities else None,
                                 "seconds_from_first_response": round(elapsed, 3) if elapsed is not None else None,
                                 "input_tokens": first_response["usage"]["input_tokens"] if first_response else None,
                             },
                             "input_per_response": {"first_tokens": rows[0]["usage"]["input_tokens"] if rows else None,
                                                    "peak_tokens": rows[peak]["usage"]["input_tokens"] if peak is not None else None,
                                                    "peak_sample_response_number": peak + 1 if peak is not None else None}})
    session_rows.sort(key=lambda row: (row["tokens"], row["session_id"]), reverse=True)
    return {"method": "linked-provider-responses-v1", **metrics(all_responses),
            "sessions_total": len(selected), "sessions_without_usage": sum(not responses[sid] for sid in selected),
            "duplicate_usage_events": duplicate_usage, "unusable_usage_events": unusable_usage,
            "tools_without_response": sum(unlinked.values()), "events_truncated": truncated,
            "rows": session_rows[:limit],
            "basis": "Separate overlapping response evidence, never added to ledger totals. Unique provider response IDs; tokens are inclusive reported input plus output. Pi tools join only by their source message ID. Categories describe linked tool-action signals; they do not establish actual bug work, token purpose, successful execution, a bug finding or accepted outcome. Source-like paths may refer to support code. Mixed responses are never split. Unsupported or missing links stay unknown; a capped event sample makes all response categories unknown. Source read/search recognizes configured source paths or extensions; other reads and opaque lab commands stay unknown. Response numbers are within this window's sample; earlier actions may be absent. First/peak input is per response, not the cumulative repeated-input total or proof of resident context."}


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
        return st_command_family(words)
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


def paired_activity_tools(events: list[Any]) -> tuple[dict, dict, set]:
    """One retained call/result pair; suppress exact nested wrapper correlations."""
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

    return tools, results, suppressed


def measured_tool_interval(tool: Any, result: Any, *, cutoff: datetime, now: datetime, session_type: str | None = None):
    duration = result.duration_ms if result is not None else tool.duration_ms
    end_event = result or tool
    timestamp = end_event.source_timestamp or end_event.created_at
    if (duration is None and session_type == "pi" and result is not None and tool.event_type == "tool_use"
            and isinstance(tool.source_timestamp, datetime) and isinstance(result.source_timestamp, datetime)
            and tool.source_timestamp.tzinfo is not None and result.source_timestamp.tzinfo is not None
            and result.source_timestamp >= tool.source_timestamp):
        # Pi records both ends of a tool call but omits duration_ms. Use the
        # native record timestamps; never infer a missing or unmatched end.
        return max(tool.source_timestamp.astimezone(UTC), cutoff), min(result.source_timestamp.astimezone(UTC), now)
    if not (isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0 and isinstance(timestamp, datetime)):
        return None
    timestamp = timestamp.astimezone(UTC)
    return max(timestamp - timedelta(milliseconds=duration), cutoff), min(timestamp, now)


def summarize_activity_cost(
    events: list[Any], cost_rows: list[Any], usage_rows: list[Any], sessions: list[Any], bindings: list[Any],
    *, cutoff: datetime, now: datetime, limit: int, truncated: bool,
) -> dict[str, Any]:
    """Combine only source-backed identities; return no prompts, commands, or tool outputs."""
    by_session = {session.id: session for session in sessions}
    events = sorted(events, key=lambda event: (event.session_id, event.turn, event.sequence))
    tools, results, suppressed = paired_activity_tools(events)

    turn_categories: dict[tuple[str, int], set[str]] = defaultdict(set)
    intervals: dict[str, list] = defaultdict(list)
    patterns: dict[str, dict] = {}
    missing_duration = 0
    transcript_rows: dict[str, list[dict]] = defaultdict(list)
    context_rows: dict[str, list[dict]] = defaultdict(list)
    tool_counts: dict[str, int] = defaultdict(int)
    missing_durations: dict[str, int] = defaultdict(int)
    session_families: dict[str, dict] = defaultdict(dict)
    for key, tool in tools.items():
        tool_counts[tool.session_id] += 1
        family, category = _tool_family(tool)
        turn_categories[(tool.session_id, tool.turn)].add("unknown" if category == "wait" else category)
        result = results.get(key)
        context_rows[tool.session_id].append(tool_context_row(tool, result, category))
        session = by_session.get(tool.session_id)
        interval = measured_tool_interval(tool, result, cutoff=cutoff, now=now,
                                          session_type=getattr(session, "session_type", None))
        measured = interval is not None
        if interval is not None:
            start, end = interval
            intervals[tool.session_id].append((start, end, category))
        else:
            missing_duration += 1
            missing_durations[tool.session_id] += 1
        returned = getattr(result, "returned_characters", None) if result is not None else None
        transcript_rows[tool.session_id].append({
            "category": category, "argument_characters": argument_characters(tool),
            "returned_characters": _number(returned), "has_returned_text": returned is not None,
        })
        if category in {"administration", "necessary_support"}:
            session_family = session_families[tool.session_id].setdefault(family, {"family": family, "calls": 0, "intervals": []})
            session_family["calls"] += 1
            if measured:
                session_family["intervals"].append((start, end, category))
            pattern = patterns.setdefault(family, {"family": family, "category": "administration", "calls": 0, "session_ids": set(), "intervals": defaultdict(list), "projects": {}})
            pattern["calls"] += 1
            pattern["session_ids"].add(tool.session_id)
            session = by_session.get(tool.session_id)
            if session is not None:
                project = pattern["projects"].setdefault(session.project_id, {
                    "project_id": session.project_id, "calls": 0, "session_ids": set(), "intervals": defaultdict(list),
                })
                project["calls"] += 1
                project["session_ids"].add(tool.session_id)
                if measured:
                    project["intervals"][tool.session_id].append((start, end, category))
            if measured:
                pattern["intervals"][tool.session_id].append((start, end, category))

    response_usage: dict[str, dict] = defaultdict(lambda: dict.fromkeys(("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens"), 0))
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
        response_usage[event.session_id]["input_tokens"] += usage["input_tokens"]
        response_usage[event.session_id]["output_tokens"] += usage["output_tokens"]
        cache = usage.get("cached_input_tokens")
        if isinstance(cache, int) and not isinstance(cache, bool) and 0 <= cache <= usage["input_tokens"]:
            response_usage[event.session_id]["cache_read_tokens"] += cache
            response_usage[event.session_id]["cache_detail_input_tokens"] += usage["input_tokens"]
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
        partitions = dict.fromkeys(("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens"), 0)
        if source in {"cost_logs", "usage_calls"}:
            row = costs[sid] if source == "cost_logs" else ledger[sid]
            partitions = usage_partitions(row)
            counts["unknown"] = partitions["input_tokens"] + partitions["output_tokens"]
        elif source == "response_events":
            counts = observed
            partitions = response_usage[sid]
        else:
            missing_usage += 1
        amount = sum(counts.values())
        coverage = token_sources.setdefault(source, {"source": source, "sessions": 0, "tokens": 0})
        coverage["sessions"] += 1
        coverage["tokens"] += amount
        source_row = costs.get(sid) if source == "cost_logs" else ledger.get(sid) if source == "usage_calls" else None
        cost = {
            "recorded_calls": _number(getattr(source_row, "calls", None)),
            "api_equiv_known_calls": _number(getattr(source_row, "api_equiv_known_calls", None)),
            "cash_known_calls": _number(getattr(source_row, "cash_known_calls", None)),
            "api_equiv_usd": getattr(source_row, "api_equiv_usd", None),
            "cash_usd": getattr(source_row, "cash_usd", None),
        }
        occupancy = _occupancy(intervals[sid])
        per_session[sid] = {"source": source, "counts": counts, "seconds": occupancy, "usage": partitions, "transcript": transcript_view(transcript_rows[sid]), "cost": cost}
        per_session[sid]["context_split"] = context_split(context_rows[sid], truncated=truncated)
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
        row = tasks.setdefault((project, task), {"project_id": project, "task_id": task, "sample_session_id": sid, "sessions": 0, "tokens": 0, "counts": dict.fromkeys(CATEGORIES, 0), "seconds": defaultdict(float), "missing_usage_sessions": 0, "transcript_rows": [], "usage": dict.fromkeys(("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens"), 0)})
        row["sessions"] += 1
        row["missing_usage_sessions"] += metrics["source"] == "missing"
        row["tokens"] += sum(metrics["counts"].values())
        row["transcript_rows"].extend(transcript_rows[sid])
        for field, value in metrics["usage"].items():
            row["usage"][field] += value
        for category, amount in metrics["counts"].items():
            row["counts"][category] += amount
        for category, amount in metrics["seconds"].items():
            row["seconds"][category] += amount

    def project_rows(pattern: dict) -> list[dict]:
        rows = [{"project_id": project["project_id"], "calls": project["calls"],
                 "sessions": len(project["session_ids"]), "sample_session_id": min(project["session_ids"]),
                 "measured_tool_seconds": round(sum(sum(_occupancy(spans).values()) for spans in project["intervals"].values()), 3)}
                for project in pattern["projects"].values()]
        rows.sort(key=lambda row: (row["measured_tool_seconds"], row["calls"], row["project_id"]), reverse=True)
        return rows[:limit]

    repeats = [{"family": family, "category": row["category"], "calls": row["calls"], "sessions": len(row["session_ids"]), "measured_tool_seconds": round(sum(sum(_occupancy(spans).values()) for spans in row["intervals"].values()), 3), "avoidable": None, "projects": project_rows(row), "projects_total": len(row["projects"])} for family, row in patterns.items() if row["calls"] > 1]
    repeats.sort(key=lambda row: (row["measured_tool_seconds"], row["calls"]), reverse=True)
    task_rows = [{"sample_session_id": row["sample_session_id"], "project_id": row["project_id"], "task_id": row["task_id"], "sessions": row["sessions"], "tokens": row["tokens"], "token_breakdown": _token_view(row["counts"])["breakdown"], "missing_usage_sessions": row["missing_usage_sessions"], "usage": row["usage"], "transcript": transcript_view(row["transcript_rows"]), "tool_time": _time_view(row["seconds"])} for row in tasks.values()]
    task_rows.sort(key=lambda row: (row["tokens"], row["tool_time"]["denominator_seconds"]), reverse=True)
    session_rows = [{"session_id": sid, "project_id": by_session[sid].project_id, "provider": by_session[sid].provider,
                     "tokens": sum(metrics["counts"].values()), "usage_source": metrics["source"], "usage": metrics["usage"], "transcript": metrics["transcript"]}
                    for sid, metrics in per_session.items()]
    session_rows.sort(key=lambda row: (row["tokens"], row["session_id"]), reverse=True)
    session_spans: dict[str, list[datetime]] = defaultdict(list)
    for event in events:
        timestamp = event.source_timestamp or event.created_at
        if isinstance(timestamp, datetime):
            session_spans[event.session_id].append(timestamp.astimezone(UTC))
    efficiency_rows = []
    for row in session_rows:
        sid = row["session_id"]
        measured_time = _time_view(per_session[sid]["seconds"])
        families = [{"family": family["family"], "calls": family["calls"],
                     "measured_tool_seconds": round(sum(_occupancy(family["intervals"]).values()), 3)}
                    for family in session_families[sid].values() if family["calls"] > 1]
        families.sort(key=lambda family: (family["measured_tool_seconds"], family["calls"], family["family"]), reverse=True)
        spans = session_spans[sid]
        efficiency_rows.append(row | {
            "model": getattr(by_session[sid], "model", None),
            "work_role": session_work_role(by_session[sid]),
            "context_split": per_session[sid]["context_split"],
            "duration_split": duration_split(per_session[sid]["seconds"], calls=tool_counts[sid], missing=missing_durations[sid], truncated=truncated),
            "tool_time": measured_time, "tools_sampled": tool_counts[sid],
            "tools_missing_duration": missing_durations[sid],
            "sampled_event_span_seconds": round((max(spans) - min(spans)).total_seconds(), 3) if spans else None,
            "goal_status": efficiency_status(measured_time, calls=tool_counts[sid], missing=missing_durations[sid], truncated=truncated),
            "repeat_admin_patterns": families[:limit], "repeat_admin_patterns_total": len(families),
        })
    projects: dict[str, dict] = {}
    for sid, metrics in per_session.items():
        project = by_session[sid].project_id
        row = projects.setdefault(project, {"project_id": project, "sessions": 0, "tokens": 0, "missing_usage_sessions": 0, "usage": dict.fromkeys(metrics["usage"], 0), "transcript_rows": []})
        row["sessions"] += 1
        row["missing_usage_sessions"] += metrics["source"] == "missing"
        row["tokens"] += sum(metrics["counts"].values())
        row["transcript_rows"].extend(transcript_rows[sid])
        for field, value in metrics["usage"].items():
            row["usage"][field] += value
    project_rankings = [{key: value for key, value in row.items() if key != "transcript_rows"} | {"transcript": transcript_view(row["transcript_rows"])} for row in projects.values()]
    project_rankings.sort(key=lambda row: (row["tokens"], row["project_id"]), reverse=True)
    unmatched_rows = [("cost_logs", row) for row in cost_rows if row.session_id not in by_session] + [("usage_calls", row) for row in usage_rows if row.session_id not in by_session]
    unmatched_usage = dict.fromkeys(("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens"), 0)
    unmatched_calls = 0
    for source, row in unmatched_rows:
        partitions = usage_partitions(row)
        amount = partitions["input_tokens"] + partitions["output_tokens"]
        tokens["unknown"] += amount
        unlinked_tokens += amount
        unmatched_calls += _number(row.calls)
        coverage = token_sources.setdefault(source, {"source": source, "sessions": 0, "tokens": 0})
        coverage["tokens"] += amount
        for field, value in partitions.items():
            unmatched_usage[field] += value
    usage_totals = {field: sum(metrics["usage"][field] for metrics in per_session.values()) + unmatched_usage[field] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cache_detail_input_tokens")}
    transcript = transcript_view([row for rows in transcript_rows.values() for row in rows])
    tool_time = _time_view(seconds)
    grouped: dict[str, dict[str, dict]] = {"project": {}, "work_role": {}, "harness": {}}
    for sid, metrics in per_session.items():
        role = session_work_role(by_session[sid])
        harness = session_harness(by_session[sid])
        for dimension, identity, label in (("harness", harness, HARNESSES[harness]["label"] if harness in HARNESSES else "Unknown"),
                                            ("project", by_session[sid].project_id, by_session[sid].project_id),
                                            ("work_role", role["id"] if role else "unknown", role["label"] if role else "Unknown")):
            group = grouped[dimension].setdefault(identity, {
                f"{dimension}_id": identity, "label": label, "sessions": 0,
                "seconds": defaultdict(float), "calls": 0, "missing": 0,
                "context_splits": [],
                "usage": dict.fromkeys(metrics["usage"], 0), "missing_usage_sessions": 0,
                "cost": {"recorded_calls": 0, "api_equiv_known_calls": 0, "cash_known_calls": 0, "api_equiv_usd": None, "cash_usd": None},
            })
            group["sessions"] += 1
            group["context_splits"].append(metrics["context_split"])
            group["missing_usage_sessions"] += metrics["source"] == "missing"
            for field, amount in metrics["usage"].items():
                group["usage"][field] += amount
            for field, amount in metrics["cost"].items():
                if amount is not None:
                    group["cost"][field] = (group["cost"][field] or 0) + amount
            group["calls"] += tool_counts[sid]
            group["missing"] += missing_durations[sid]
            for category, value in metrics["seconds"].items():
                group["seconds"][category] += value
    def group_rows(dimension: str) -> list[dict]:
        return [{f"{dimension}_id": row[f"{dimension}_id"], "label": row["label"], "sessions": row["sessions"],
                 "usage": row["usage"], "cost": row["cost"],
                 "context_split": combine_context_splits(row["context_splits"], truncated=truncated),
                 "coverage": {"usage_sessions": row["sessions"] - row["missing_usage_sessions"], "missing_usage_sessions": row["missing_usage_sessions"]},
                 "duration_split": duration_split(row["seconds"], calls=row["calls"], missing=row["missing"], truncated=truncated)}
                for _, row in sorted(grouped[dimension].items())]
    shares = {row["category"]: row["share"] for row in tool_time["breakdown"]}
    summary = "No measured tool-runtime intervals in this window."
    if tool_time["denominator_seconds"]:
        summary = f"Of {tool_time['denominator_seconds']:g} measured active tool seconds: {shares['substantive']:.0%} substantive, {shares['administration']:.0%} administration including support, {shares['unknown']:.0%} unknown including mixed. Thinking and idle time are unmeasured."
    return {
        "scope": "Windowed recorded usage across providers, including accounting without a matching Hub session. Hub sessions created/updated or with events/accounting in the window remain visible even without usage. Rankings cover Hub-linked usage only.",
        "window_start": cutoff.isoformat(), "window_end": now.isoformat(),
        "sessions": len(by_session), "events_sampled": len(events), "event_limit": EVENT_LIMIT,
        "events_truncated": truncated, "missing_usage_sessions": missing_usage,
        "unlinked_sessions": unlinked, "overlapping_sources_excluded": overlaps,
        "unlinked_tokens": unlinked_tokens, "unlinked_tool_seconds": round(unlinked_tool_seconds, 3),
        "tokens": _token_view(tokens, list(token_sources.values())),
        "usage": usage_totals,
        "unmatched_accounting_tokens": unmatched_usage["input_tokens"] + unmatched_usage["output_tokens"],
        "unmatched_accounting_calls": unmatched_calls,
        "transcript": transcript,
        "st_commands": summarize_st_commands(tools, results, sessions=by_session, limit=limit),
        "hunter_responses": hunter_response_activity(events, tools, by_session, cutoff=cutoff, now=now, limit=limit, truncated=truncated),
        "transcript_basis": "Estimate of sampled tool text added to history: normalized call arguments plus retained returned text, once per call. Exact nested-command wrapper correlations are suppressed. Characters are not model tokens, resident context, or causal spend. Excludes prose, system instructions, images, protocol framing and unretained output; compaction and repeated reads are not modeled.",
        "wrappers_excluded": len(suppressed & {(event.session_id, event.call_id) for event in events if event.event_type in {"tool_use", "tool_result"}}),
        "project_rankings": project_rankings[:limit], "project_rankings_total": len(project_rankings),
        "session_rankings": session_rows[:limit], "session_rankings_total": len(session_rows),
        "session_efficiency": session_efficiency(efficiency_rows, limit=limit),
        "token_basis": "One source per session, in order: cost_logs, matched usage_calls, response events. Unmatched ledger calls add to unknown globally and are excluded from Hub rankings. Ledger tokens remain unknown without a stable turn/response join. Ledger input adds disjoint cache-read/write tokens; native response input already includes cache and output includes reasoning.",
        "response_tokens": _token_view(responses),
        "response_token_basis": "Separate overlapping evidence, never added to the primary denominator: unique response IDs, scope=response, input+output (Codex input includes cache; output includes reasoning). Category describes all observed tools in the normalized user turn, not exact per-command cost or the intent of every token.",
        "duration_split": duration_split(seconds, calls=len(tools), missing=missing_duration, truncated=truncated),
        "context_split": combine_context_splits([metrics["context_split"] for metrics in per_session.values()], truncated=truncated),
        "by_project": group_rows("project"), "by_work_role": group_rows("work_role"), "by_harness": group_rows("harness"),
        "work_roles": work_role_options(), "harnesses": harness_options(),
        "tool_time": tool_time, "tools_missing_duration": missing_duration, "tools_sampled": len(tools),
        "summary": summary, "repeat_admin_patterns": repeats[:limit], "repeat_admin_patterns_total": len(repeats),
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


async def build_activity_cost_snapshot(
    db: AsyncSession, *, cutoff: datetime, now: datetime, limit: int,
    project_id: str | None = None, provider: str | None = None, model: str | None = None, session_id: str | None = None,
    work_role: str | None = None, harness: str | None = None, list_filters: Any = None,
) -> dict[str, Any]:
    """Bound event memory, aggregate ledgers in SQL, and include old-but-active sessions."""
    event_time = func.coalesce(SessionEvent.source_timestamp, SessionEvent.created_at)
    filters = []
    for column, value in ((Session.project_id, project_id), (Session.provider, provider), (Session.model, model), (Session.id, session_id)):
        if value is not None:
            filters.append(column == value)
    if list_filters is not None:
        from app.services.session_queries import session_list_predicates
        filters.extend(session_list_predicates(list_filters))
    if work_role is not None:
        filters.append(role_predicate(work_role))
    if harness is not None:
        filters.append(harness_predicate(harness))
    selected_sessions = select(Session.id).where(*filters)
    returned_characters = returned_characters_expression(SessionEvent)
    events = (await db.execute(select(
        SessionEvent.id, SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence,
        SessionEvent.event_type, SessionEvent.call_id, SessionEvent.tool_name, SessionEvent.tool_input, SessionEvent.source_event_id,
        returned_characters, SessionEvent.usage, SessionEvent.duration_ms, SessionEvent.source_timestamp, SessionEvent.created_at,
    ).where(event_time >= cutoff, event_time < now, SessionEvent.event_type.in_(["tool_use", "tool_result", "usage"]),
            *([SessionEvent.session_id.in_(selected_sessions)] if filters else []))
        .order_by(event_time.desc(), SessionEvent.id).limit(EVENT_LIMIT + 1))).all()
    cost_rows = (await db.execute(select(
        CostLog.session_id, func.sum(CostLog.input_tokens + CostLog.cache_read_tokens + CostLog.cache_write_tokens).label("input_tokens"),
        func.sum(CostLog.output_tokens).label("output_tokens"), func.count().label("calls"),
        func.sum(CostLog.api_equiv_usd).label("api_equiv_usd"), func.count(CostLog.api_equiv_usd).label("api_equiv_known_calls"),
        func.sum(CostLog.cost_usd).label("cash_usd"), func.count(CostLog.cost_usd).label("cash_known_calls"),
        func.sum(CostLog.cache_read_tokens).label("cache_read_tokens"), func.sum(CostLog.cache_write_tokens).label("cache_write_tokens"),
    ).where(CostLog.created_at >= cutoff, CostLog.created_at < now,
            *([CostLog.session_id.in_(selected_sessions)] if filters else [])).group_by(CostLog.session_id))).all()
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
        func.sum(UsageCall.api_equiv_usd).label("api_equiv_usd"), func.count(UsageCall.api_equiv_usd).label("api_equiv_known_calls"),
        func.sum(UsageCall.cached_input_tokens).label("cache_read_tokens"), func.sum(UsageCall.cache_write_tokens).label("cache_write_tokens"),
    ).select_from(UsageCall).outerjoin(Session, (Session.id == native_id) & (native_provider == UsageCall.provider))
        .where(UsageCall.occurred_at >= cutoff, UsageCall.occurred_at < now, *filters).group_by(Session.id))).all()
    ids = {row.session_id for row in [*events[:EVENT_LIMIT], *cost_rows, *usage_rows]}
    sessions = (await db.execute(select(Session.id, Session.project_id, Session.provider, Session.model, Session.provider_metadata, Session.request_source, Session.session_type, Session.created_at).where(or_(
        Session.id.in_(ids), (Session.created_at >= cutoff) & (Session.created_at < now),
        (Session.updated_at >= cutoff) & (Session.updated_at < now),
    ), *filters))).all()
    ids = {session.id for session in sessions}
    bindings = (await db.execute(select(SessionBinding.session_id, SessionBinding.project_id, SessionBinding.task_id)
        .where(SessionBinding.session_id.in_(ids), SessionBinding.task_id.is_not(None)))).all() if ids else []
    return await asyncio.to_thread(summarize_activity_cost, events[:EVENT_LIMIT], cost_rows, usage_rows, sessions, bindings,
        cutoff=cutoff, now=now, limit=limit, truncated=len(events) > EVENT_LIMIT)
