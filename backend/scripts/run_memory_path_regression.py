#!/usr/bin/env python3
"""Run real-path memory behavior checks across Codex and Agent Hub agents."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("MEMORY_PATH_REGRESSION_NO_REEXEC") != "1"
):
    os.environ["MEMORY_PATH_REGRESSION_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])


STARTUP_COMMANDS_PROMPT = (
    "An engineering task in this repo is about to begin. Without running any commands, return only JSON with keys "
    "closeout_check_cmd, repo_symbol_search_cmd, memory_lookup_cmd, quality_check_cmd. "
    "Use the command you would reach for first in that situation, based only on startup context."
)
COMMIT_RULE_PROMPT = (
    "I vaguely remember there is a memory about the canonical git commit workflow, "
    "but not the exact rule. Follow your memory-handling instructions before answering. "
    "Use tools if needed. Return only JSON with keys lookup_cmds, checkpoint_requirement, "
    "preferred_commit_path, raw_git_commit_preferred."
)
PROMPT_SOURCE_PROMPT = (
    "I vaguely remember there is a rule about where runtime prompt instructions should live, "
    "but not the exact wording. Follow your memory-handling instructions before answering. "
    "Use tools if needed. Return only JSON with keys lookup_cmds, durable_prompt_source, "
    "checked_in_markdown_authoritative, action_for_stale_markdown."
)


@dataclass
class ProbeResult:
    target: str
    case: str
    status: str
    reasons: list[str]
    data: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunnerResult:
    data: dict[str, Any]
    evidence: dict[str, Any]


def _run_command(
    args: list[str],
    *,
    stdin_text: str | None = None,
    timeout: int = 180,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=stdin_text,
        text=True,
        capture_output=True,
        cwd=cwd,
        timeout=timeout,
        check=False,
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError(f"Unable to extract JSON object from output: {text[:300]}")


def _parse_codex_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    final_text: str | None = None
    commands: list[str] = []
    raw_events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        raw_events.append(event)
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message":
                final_text = item.get("text")
            if item.get("type") == "command_execution":
                command = item.get("command")
                if isinstance(command, str):
                    commands.append(command)
        elif event.get("type") == "item.started" and isinstance(item, dict):
            if item.get("type") == "command_execution":
                command = item.get("command")
                if isinstance(command, str):
                    commands.append(command)
    if not final_text:
        raise ValueError(f"Codex output missing final agent message: {stdout[:400]}")
    return _extract_json_object(final_text), {
        "commands": sorted(set(commands)),
        "event_count": len(raw_events),
    }


def _run_codex_yolo(prompt: str) -> RunnerResult:
    result = _run_command(
        ["codex", "exec", "--json", "--yolo", prompt],
        timeout=240,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    data, evidence = _parse_codex_jsonl(result.stdout)
    return RunnerResult(data=data, evidence=evidence)


def _run_agent_hub(agent_slug: str, prompt: str, *, execute_tools: bool) -> RunnerResult:
    args = ["st", "complete", "-a", agent_slug, "-p", "agent-hub", "--raw", "-n", "3", prompt]
    if execute_tools:
        args.insert(-1, "-x")
    result = _run_command(args, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    payload = json.loads(result.stdout)
    data = _extract_json_object(payload["content"])
    progress_log = payload.get("progress_log") or []
    return RunnerResult(
        data=data,
        evidence={
            "tool_calls_count": payload.get("tool_calls_count", 0),
            "progress_log": progress_log,
            "session_id": payload.get("session_id"),
        },
    )


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _commands_from_progress_log(progress_log: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for entry in progress_log:
        for tool_call in entry.get("tool_calls") or []:
            input_data = tool_call.get("input") or {}
            command = input_data.get("command")
            if isinstance(command, str):
                commands.append(command)
            elif tool_call.get("name") == "consult_agent":
                agent_slug = input_data.get("agent_slug")
                if isinstance(agent_slug, str):
                    commands.append(f"consult_agent:{agent_slug}")
    return commands


def _validate_startup_commands(target: str, result: RunnerResult) -> ProbeResult:
    data = result.data
    reasons: list[str] = []
    if not _string(data.get("closeout_check_cmd")).startswith("st cleanup status"):
        reasons.append("closeout_check_cmd should be `st cleanup status`")
    if not _string(data.get("repo_symbol_search_cmd")).startswith("st search"):
        reasons.append("repo_symbol_search_cmd should start with `st search`")
    memory_lookup_cmd = _string(data.get("memory_lookup_cmd"))
    if not (
        memory_lookup_cmd.startswith("st memory search")
        or memory_lookup_cmd.startswith("st memory get")
    ):
        reasons.append("memory_lookup_cmd should start with `st memory search` or `st memory get`")
    if not _string(data.get("quality_check_cmd")).startswith("st check"):
        reasons.append("quality_check_cmd should start with `st check`")
    status = "pass" if not reasons else "fail"
    return ProbeResult(target=target, case="startup_commands", status=status, reasons=reasons, data=data, evidence=result.evidence)


def _validate_commit_rule(target: str, result: RunnerResult) -> ProbeResult:
    data = result.data
    reasons: list[str] = []
    warnings: list[str] = []
    checkpoint_requirement = _string(data.get("checkpoint_requirement"))
    preferred_commit_path = _string(data.get("preferred_commit_path"))
    lookup_cmds = _list_of_strings(data.get("lookup_cmds"))
    if data.get("raw_git_commit_preferred") is not False:
        reasons.append("raw_git_commit_preferred must be false")
    if (
        "git status --short --branch" not in checkpoint_requirement
        and not any("git status --short --branch" in command for command in lookup_cmds)
    ):
        reasons.append("checkpoint_requirement should mention `git status --short --branch`")
    if "/commit_it" not in preferred_commit_path and "commit.sh" not in preferred_commit_path:
        reasons.append("preferred_commit_path should mention `/commit_it` or `commit.sh`")

    evidence_commands = result.evidence.get("commands") or _commands_from_progress_log(result.evidence.get("progress_log") or [])
    command_text = "\n".join(lookup_cmds + evidence_commands)
    if "st memory get 919e883f" not in command_text and "st memory search" not in command_text:
        reasons.append("exact-rule memory lookup was not evident")
    elif "consult_agent" in command_text and "st memory get 919e883f" not in command_text:
        warnings.append("used consult_agent for commit rule instead of direct `st memory get 919e883f`")

    status = "fail" if reasons else ("warn" if warnings else "pass")
    return ProbeResult(
        target=target,
        case="commit_rule",
        status=status,
        reasons=reasons + warnings,
        data=data,
        evidence={**result.evidence, "commands": evidence_commands},
    )


def _validate_prompt_source(target: str, result: RunnerResult) -> ProbeResult:
    data = result.data
    reasons: list[str] = []
    warnings: list[str] = []
    durable_prompt_source = _string(data.get("durable_prompt_source")).lower()
    stale_markdown_action = _string(data.get("action_for_stale_markdown")).lower()
    if data.get("checked_in_markdown_authoritative") is not False:
        reasons.append("checked_in_markdown_authoritative must be false")
    if (
        "db" not in durable_prompt_source
        and "database" not in durable_prompt_source
        and "postgres" not in durable_prompt_source
        and "prompts table" not in durable_prompt_source
    ):
        reasons.append("durable_prompt_source should mention DB-backed prompts")
    if "delete" not in stale_markdown_action:
        reasons.append("action_for_stale_markdown should say to delete stale markdown")

    lookup_cmds = _list_of_strings(data.get("lookup_cmds"))
    evidence_commands = result.evidence.get("commands") or _commands_from_progress_log(result.evidence.get("progress_log") or [])
    command_text = "\n".join(lookup_cmds + evidence_commands)
    exact_prompt_memory_ids = ("823f8549", "a416f8ce", "f1e7cfee", "15a165e7", "d6f5ec92", "c4f0b1a1")
    if not any(memory_id in command_text for memory_id in exact_prompt_memory_ids):
        reasons.append("prompt-source answer lacked evidence of exact memory expansion")
    elif "consult_agent" in command_text and not any(f"st memory get {memory_id}" in command_text for memory_id in exact_prompt_memory_ids):
        warnings.append("used consult_agent for prompt-source rule instead of direct `st memory get`")

    status = "fail" if reasons else ("warn" if warnings else "pass")
    return ProbeResult(
        target=target,
        case="prompt_source",
        status=status,
        reasons=reasons + warnings,
        data=data,
        evidence={**result.evidence, "commands": evidence_commands},
    )


def _run_probe(
    *,
    target: str,
    prompt: str,
    runner: Callable[[], RunnerResult],
    validator: Callable[[str, RunnerResult], ProbeResult],
) -> ProbeResult:
    try:
        return validator(target, runner())
    except Exception as exc:
        return ProbeResult(target=target, case=prompt, status="fail", reasons=[str(exc)])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run memory path regression checks")
    parser.add_argument(
        "--agents",
        default="coder,reviewer,persona,debugger",
        help="Comma-separated Agent Hub agent slugs to probe",
    )
    parser.add_argument("--skip-codex", action="store_true", help="Skip Codex --yolo probes")
    parser.add_argument("--skip-agents", action="store_true", help="Skip Agent Hub agent probes")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    return parser


def _summarize(results: list[ProbeResult]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return {
        "counts": counts,
        "all_passed": counts["fail"] == 0 and counts["warn"] == 0,
        "results": [asdict(result) for result in results],
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    results: list[ProbeResult] = []

    if not args.skip_codex:
        results.append(
            _run_probe(
                target="codex_yolo",
                prompt="startup_commands",
                runner=lambda: _run_codex_yolo(STARTUP_COMMANDS_PROMPT),
                validator=_validate_startup_commands,
            )
        )
        results.append(
            _run_probe(
                target="codex_yolo",
                prompt="commit_rule",
                runner=lambda: _run_codex_yolo(COMMIT_RULE_PROMPT),
                validator=_validate_commit_rule,
            )
        )
        results.append(
            _run_probe(
                target="codex_yolo",
                prompt="prompt_source",
                runner=lambda: _run_codex_yolo(PROMPT_SOURCE_PROMPT),
                validator=_validate_prompt_source,
            )
        )

    if not args.skip_agents:
        agent_slugs = [slug.strip() for slug in args.agents.split(",") if slug.strip()]
        for agent_slug in agent_slugs:
            results.append(
                _run_probe(
                    target=f"agent:{agent_slug}",
                    prompt="commit_rule",
                    runner=lambda slug=agent_slug: _run_agent_hub(slug, COMMIT_RULE_PROMPT, execute_tools=True),
                    validator=_validate_commit_rule,
                )
            )
            results.append(
                _run_probe(
                    target=f"agent:{agent_slug}",
                    prompt="prompt_source",
                    runner=lambda slug=agent_slug: _run_agent_hub(slug, PROMPT_SOURCE_PROMPT, execute_tools=True),
                    validator=_validate_prompt_source,
                )
            )

    summary = _summarize(results)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("Memory path regression summary")
        print(json.dumps(summary["counts"], indent=2))
        for result in results:
            marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[result.status]
            print(f"{marker} {result.target} {result.case}")
            for reason in result.reasons:
                print(f"  - {reason}")
    raise SystemExit(0 if summary["counts"]["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
