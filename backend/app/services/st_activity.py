"""Content-free ST observations over the existing deduplicated event sample.

Shell syntax is deliberately bounded. A shared shell result never becomes a
made-up per-command duration or output. No arguments or output are returned.
"""

from __future__ import annotations

import json
import math
import shlex
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any

import tiktoken

POLICY = json.loads(Path(__file__).with_name("activity_policy.json").read_text())
_FAMILIES = {verb: category for category, verbs in POLICY["st_families"].items() for verb in verbs}


def shell_segments(command: str) -> list[list[str]] | None:
    # Split only unquoted foreground operators; shlex then decodes each argv.
    # Unsupported syntax stays unparsed rather than inventing ST observations.
    segments: list[list[str]] = []
    quote = None
    escaped = False
    start = index = 0
    last_operator = None
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char == quote:
            quote = None
        elif char in {"'", '"'} and quote is None:
            quote = char
        elif quote != "'" and char in {"$", "`"}:
            return None
        elif quote is None:
            if char in "<>()#":
                return None
            if char in ";&|\n":
                operator = command[index:index + 2]
                if char == "&" and operator != "&&":
                    return None
                part = command[start:index].strip()
                if not part:
                    return None
                if part:
                    try:
                        segments.append(shlex.split(part))
                    except ValueError:
                        return None
                index += int(operator in {"&&", "||"})
                last_operator = operator if operator in {"&&", "||"} else char
                start = index + 1
        index += 1
    if quote or escaped:
        return None
    try:
        tail = shlex.split(command[start:])
    except ValueError:
        return None
    if tail:
        segments.append(tail)
    elif last_operator in {"&&", "||", "|"}:
        return None
    if any(segment[0] in {"if", "then", "for", "while", "do", "case", "function", "!"} for segment in segments):
        return None
    if len(segments) == 1 and len(segments[0]) == 3:
        executable, flag, script = segments[0]
        if PurePosixPath(executable).name in {"bash", "sh", "zsh"} and flag in {"-c", "-lc"}:
            return shell_segments(script)
    return segments


def _commands(tool: Any) -> list[list[str]] | None:
    data = tool.tool_input if isinstance(tool.tool_input, dict) else {}
    command = data.get("command", data.get("cmd"))
    if isinstance(command, list) and all(isinstance(part, str) for part in command):
        # Native command arrays are argv, not shell source.
        if len(command) == 3 and PurePosixPath(command[0]).name in {"bash", "sh", "zsh"} and command[1] in {"-c", "-lc"}:
            return shell_segments(command[2])
        return [command] if command else []
    return shell_segments(command) if isinstance(command, str) else None


def st_command_family(words: list[str]) -> tuple[str, str]:
    args = words[1:]
    while args:
        if args[0] in {"-P", "--project"}:
            args = args[2:]
        elif args[0].startswith(("--project=", "-P")) or args[0] in {"--json", "--no-compact", "--compact", "-c", "--human", "--progress-only"}:
            args = args[1:]
        else:
            break
    verb = args[0] if args else "help"
    # Only policy-owned family labels leave this module, never arbitrary argv.
    return (f"st.{verb}", _FAMILIES[verb]) if verb in _FAMILIES else ("st.unknown", "unknown")


@cache
def _encoding() -> tiktoken.Encoding:
    # Same reference encoding as the existing token counter. Run off the event loop.
    return tiktoken.get_encoding(POLICY["input_token_encoding"])


def _metrics() -> dict:
    return dict.fromkeys(("commands", "measured_seconds", "input_tokens_estimate", "output_tokens_estimate",
                          "commands_with_tokenized_input", "commands_with_duration", "commands_with_output", "shared_commands"), 0)


def summarize_st_commands(tools: dict, results: dict, *, sessions: dict, limit: int) -> dict:
    totals = _metrics()
    families: dict[tuple[str, str], dict] = {}
    shell_calls = unparsed = calls_with_st = 0
    remaining = POLICY["max_tokenized_characters_per_snapshot"]
    for key, tool in tools.items():
        if tool.event_type != "tool_use" or (tool.tool_name or "").split(".")[-1].lower() not in {"bash", "exec_command", "run_command"}:
            continue
        shell_calls += 1
        commands = _commands(tool)
        if commands is None:
            unparsed += 1
            continue
        st = [words for words in commands if words and PurePosixPath(words[0]).name == "st"]
        calls_with_st += bool(st)
        for words in st:
            family, category = st_command_family(words)
            session = sessions.get(tool.session_id)
            row = families.setdefault((family, category), {
                "family": family, "category": category, **_metrics(),
                "sample_session_id": session.id if session is not None else None,
                "sample_project_id": session.project_id if session is not None else None,
            })
            shared = len(commands) != 1
            result = results.get(key)
            duration = getattr(result, "duration_ms", None) if result is not None else tool.duration_ms
            has_duration = not shared and isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0
            returned = getattr(result, "returned_characters", None)
            has_output = not shared and isinstance(returned, int) and not isinstance(returned, bool) and returned >= 0
            normalized = shlex.join(words)
            tokenized = len(normalized) <= min(POLICY["max_tokenized_characters_per_command"], remaining)
            if tokenized:
                input_tokens = len(_encoding().encode(normalized, disallowed_special=()))
                remaining -= len(normalized)
            else:
                input_tokens = math.ceil(len(normalized) / POLICY["output_characters_per_token"])
            metrics = {
                "commands": 1, "shared_commands": int(shared),
                "input_tokens_estimate": input_tokens, "commands_with_tokenized_input": int(tokenized),
                "output_tokens_estimate": math.ceil(returned / POLICY["output_characters_per_token"]) if has_output else 0,
                "measured_seconds": int(duration) / 1000 if has_duration else 0,
                "commands_with_duration": int(has_duration), "commands_with_output": int(has_output),
            }
            for field, amount in metrics.items():
                row[field] += amount
                totals[field] += amount
    rows = sorted(families.values(), key=lambda row: (
        row["input_tokens_estimate"] + row["output_tokens_estimate"], row["measured_seconds"], row["family"],
    ), reverse=True)
    for row in [totals, *rows]:
        row["measured_seconds"] = round(row["measured_seconds"], 3)
    return {
        **totals, "shell_calls": shell_calls, "shell_calls_unparsed": unparsed, "calls_with_st": calls_with_st,
        "administration_commands": sum(row["commands"] for row in rows if row["category"] in {"administration", "necessary_support"}),
        "substantive_commands": sum(row["commands"] for row in rows if row["category"] == "substantive"),
        "unknown_commands": sum(row["commands"] for row in rows if row["category"] == "unknown"),
        "families": rows[:limit], "families_total": len(rows),
        "input_token_encoding": POLICY["input_token_encoding"],
        "output_characters_per_token": POLICY["output_characters_per_token"],
        "count_basis": "Recognizable ST commands in sampled shell source, not proof of execution. Conditional commands may not run; scripts and unsupported syntax can hide more commands.",
        "input_token_basis": "Reference tokenizer on normalized ST command argv within per-command and per-snapshot character budgets. Beyond either budget, ceiling of normalized characters / output_characters_per_token; commands_with_tokenized_input exposes method coverage. Excludes tool JSON framing and other shell text; text estimate, not provider usage.",
        "output_token_basis": f"Ceiling of retained returned characters / {POLICY['output_characters_per_token']} per isolated invocation, matching ST tools cost's character approximation. Output contents are not fetched or tokenized. Language and formatting change accuracy; missing, truncated or shared output has unknown size.",
        "time_basis": "Sum of reported elapsed durations for isolated ST commands, including zero. Concurrent calls add; this is not union occupancy or agent thinking time. Shared shell durations are unallocated.",
    }
