#!/usr/bin/env python3
"""Run a direct Claude CLI worker and ingest its transcript into Agent Hub."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("CLAUDE_ORCHESTRATOR_NO_REEXEC") != "1"
):
    os.environ["CLAUDE_ORCHESTRATOR_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a direct Claude CLI worker and ingest the resulting transcript.",
    )
    parser.add_argument("--prompt-file", help="Markdown/text prompt file for Claude")
    parser.add_argument(
        "--spec-file",
        help="Optional JSON worker spec that generates a stable readonly prompt and agents payload",
    )
    parser.add_argument("--schema-file", help="Optional JSON schema file for StructuredOutput")
    parser.add_argument("--agents-file", help="Optional Claude agents JSON file")
    parser.add_argument(
        "--task-id",
        help="Optional SummitFlow task id to convert into a Claude worker contract",
    )
    parser.add_argument(
        "--feedback-text",
        help="Optional evaluator feedback to inject into a task-driven Claude contract",
    )
    parser.add_argument(
        "--task-root",
        help="Repo root where `st context` / `st claim` should run for --task-id",
    )
    parser.add_argument(
        "--claim-if-needed",
        dest="claim_if_needed",
        action="store_true",
        default=None,
        help="Claim the task automatically when --task-id is used and no checkpoint exists yet",
    )
    parser.add_argument(
        "--no-claim-if-needed",
        dest="claim_if_needed",
        action="store_false",
        help="Do not auto-claim when --task-id is used and the task has no checkpoint yet",
    )
    parser.add_argument("--project-id", default="agent-hub", help="Agent Hub project id")
    parser.add_argument(
        "--source",
        default="st-cli",
        help="Caller/source label for observability and wrapper provenance",
    )
    parser.add_argument("--workdir", default=str(ROOT), help="Working directory for the Claude run")
    parser.add_argument("--model", default="sonnet", help="Claude model alias")
    parser.add_argument("--effort", help="Claude effort override (low, medium, high, max)")
    parser.add_argument(
        "--append-system-prompt",
        help="Optional system prompt appended to Claude's built-in system prompt",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Claude skill to invoke at session start (repeatable)",
    )
    parser.add_argument(
        "--allowed-tools",
        default="Read,Agent,StructuredOutput",
        help="Comma-separated Claude allowed tools",
    )
    parser.add_argument(
        "--permission-mode",
        default="bypassPermissions",
        help="Claude permission mode (default: bypassPermissions)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Subprocess timeout in seconds",
    )
    parser.add_argument(
        "--batch-task-id",
        action="append",
        default=[],
        help="Task id linked to a prompt-file orchestrator batch (repeatable)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip Agent Hub transcript ingestion and only emit raw artifacts",
    )
    args = parser.parse_args()
    task_modes = sum(
        1 for value in (args.prompt_file, args.spec_file, args.task_id) if value
    )
    if task_modes != 1:
        parser.error("exactly one of --prompt-file, --spec-file, or --task-id is required")
    if args.task_id and not args.task_root:
        parser.error("--task-root is required when --task-id is used")
    if args.task_id:
        args.claim_if_needed = True if args.claim_if_needed is None else args.claim_if_needed
    elif args.claim_if_needed is None:
        args.claim_if_needed = False
    return args


def _run_async(awaitable):
    global _ASYNC_LOOP
    if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
        _ASYNC_LOOP = asyncio.new_event_loop()
    return _ASYNC_LOOP.run_until_complete(awaitable)


def _read_text(path_str: str) -> str:
    return Path(path_str).read_text().strip()


def _apply_skills_to_prompt(prompt: str, skills: list[str] | None) -> str:
    normalized = [skill.strip().lstrip("/") for skill in skills or [] if isinstance(skill, str) and skill.strip()]
    if not normalized:
        return prompt
    skill_block = "\n".join(f"/{skill}" for skill in normalized)
    return f"{skill_block}\n\n{prompt}".strip()


def _read_json_object(path_str: str) -> dict[str, Any]:
    parsed = json.loads(Path(path_str).read_text())
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object in {path_str}")
    return parsed


def _read_agents_payload(path: Path) -> str:
    raw = path.read_text().strip()
    try:
        return json.dumps(json.loads(raw), separators=(",", ":"))
    except json.JSONDecodeError:
        return raw


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _subprocess_env() -> dict[str, str]:
    """Return a sanitized env for nested CLI subprocesses."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


def _run_text_command(*, command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
        env=_subprocess_env(),
    )
    return completed.stdout


def _parse_task_context(raw: str) -> dict[str, Any]:
    context: dict[str, Any] = {
        "done_when": [],
        "context_entries": [],
    }
    for line in raw.splitlines():
        if line.startswith("TASK:"):
            task_parts = line.removeprefix("TASK:").split("|")
            if task_parts:
                context["task_id"] = task_parts[0]
            if len(task_parts) > 1:
                context["task_status"] = task_parts[1]
            if len(task_parts) > 3:
                context["task_type"] = task_parts[3]
        elif line.startswith("TITLE:"):
            context["title"] = line.removeprefix("TITLE:").strip()
        elif line.startswith("DESCRIPTION:"):
            context["description"] = line.removeprefix("DESCRIPTION:").strip()
        elif line.startswith("DONE_WHEN"):
            _, _, value = line.partition(":")
            context["done_when"] = [
                item.strip() for item in value.split(" | ") if item.strip()
            ]
        elif line.startswith("CONTEXT:"):
            _, _, value = line.partition(":")
            mode, _, path = value.partition(":")
            context["context_entries"].append(
                {
                    "mode": mode.strip(),
                    "path": path.strip(),
                }
            )
        elif line.startswith("PROJECT_ROOT:"):
            context["project_root"] = line.removeprefix("PROJECT_ROOT:").strip()
        elif line.startswith("TASK_BRANCH:"):
            context["task_branch"] = line.removeprefix("TASK_BRANCH:").strip()
    return context


def _normalize_target_path(*, workdir: Path, raw_path: str) -> str | None:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workdir / candidate).resolve()
    try:
        relative = resolved.relative_to(workdir.resolve())
    except ValueError:
        return None
    if not resolved.exists():
        return None
    return str(relative)


def _find_target_paths(task_context: dict[str, Any], *, workdir: Path) -> list[str]:
    targets: list[str] = []
    for entry in task_context.get("context_entries", []):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        normalized = _normalize_target_path(workdir=workdir, raw_path=path)
        if normalized:
            targets.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for path in targets:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _discover_related_tests(*, workdir: Path, target_paths: list[str], limit: int = 4) -> list[str]:
    tests_root = workdir / "backend" / "tests"
    if not tests_root.exists():
        return []

    exact_matches: list[str] = []
    content_matches: list[str] = []
    for target_path in target_paths:
        stem = Path(target_path).stem
        for path in sorted(tests_root.rglob(f"test_{stem}.py")):
            rel = str(path.relative_to(workdir))
            if rel not in exact_matches:
                exact_matches.append(rel)

        search_terms = {stem, target_path}
        for path in sorted(tests_root.rglob("test_*.py")):
            rel = str(path.relative_to(workdir))
            if rel in exact_matches or rel in content_matches:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if any(term in raw for term in search_terms):
                content_matches.append(rel)

    return (exact_matches + content_matches)[:limit]


def _task_allowed_tools() -> str:
    return "Read,Agent,Edit,MultiEdit,Write,Bash,Glob,Grep,LS"


def _task_agents_payload() -> dict[str, Any]:
    return {
        "task-analyst": {
            "description": "Scoped read-only task analyst",
            "prompt": (
                "Read only the requested task files and tests. Identify the safest "
                "extraction seams, behavior-sensitive logic, likely regressions, "
                "and the tests that should be rerun. Do not edit files."
            ),
            "tools": ["Read", "Grep", "Glob", "LS"],
            "model": "sonnet",
        }
    }


def _build_prompt_from_task_context(
    task_context: dict[str, Any],
    *,
    project_id: str,
    workdir: Path,
    target_paths: list[str],
    related_tests: list[str],
    feedback_text: str | None = None,
) -> str:
    task_id = task_context.get("task_id", "unknown-task")
    title = task_context.get("title", "Untitled task")
    description = task_context.get("description", "")
    done_when = task_context.get("done_when", [])
    task_type = task_context.get("task_type", "")

    lines = [
        f"You are working in the `{project_id}` shared project checkout.",
        "",
        "Task:",
        f"- ID: `{task_id}`",
        f"- Title: `{title}`",
    ]

    if isinstance(description, str) and description:
        lines.extend(["", "Objective:", f"- {description}"])

    if done_when:
        lines.extend(["", "Done when:"])
        lines.extend(f"- {item}" for item in done_when if isinstance(item, str) and item)

    if isinstance(feedback_text, str) and feedback_text.strip():
        lines.extend(
            [
                "",
                "Evaluator feedback from the previous pass:",
                f"- {feedback_text.strip()}",
            ]
        )

    lines.extend(
        [
            "",
            "Required workflow:",
            "1. Use exactly one Agent subagent named `task-analyst` for a read-only analysis pass before editing.",
        ]
    )
    if target_paths or related_tests:
        lines.append("2. Have that subagent read only these files:")
        for path in target_paths:
            lines.append(f"   - `{path}`")
        for path in related_tests:
            lines.append(f"   - `{path}`")
    else:
        lines.append(
            "2. Have that subagent analyze the files most relevant to the task before editing."
        )
    lines.extend(
        [
            "3. Main agent implements the task after using the subagent findings.",
            "4. Run the required verification before finishing.",
            "",
            "Hard constraints:",
        ]
    )

    if target_paths:
        if len(target_paths) == 1:
            lines.append(
                f"- Edit `{target_paths[0]}` only unless a narrow additional file change is genuinely required to keep the task correct."
            )
        else:
            lines.append("- Limit edits to these task target files unless a narrow extra fix is genuinely required:")
            lines.extend(f"  - `{path}`" for path in target_paths)
    lines.extend(
        [
            "- Preserve existing behavior unless the task explicitly requires behavior change.",
            "- No stubs, placeholders, TODOs, compatibility shims, or unrelated cleanup.",
            f"- Stay inside this claimed checkout: `{workdir}`.",
            "- Do not read, edit, commit, or run commands in sibling repos or any path outside this checkout. If the task appears mis-scoped, stop and report the mismatch instead of switching repos.",
        ]
    )
    if task_type == "refactor":
        lines.append("- Prefer helper extraction, reduced nesting, and removal of duplicate logic over cosmetic rearrangement.")

    verification_commands: list[str] = []
    if related_tests:
        verification_commands.append(f"dt pytest {' '.join(related_tests)}")
    verification_commands.append("dt --quick --changed-only")
    lines.extend(["", "Verification commands:"])
    lines.extend(f"- `{command}`" for command in verification_commands)

    lines.extend(
        [
            "",
            "Final response must include:",
            "- files changed",
            "- the main structural or behavioral work completed",
            "- exact verification commands run",
            "- whether all verifications passed",
        ]
    )
    return "\n".join(lines)


def _load_task_contract(
    *,
    task_id: str,
    project_id: str,
    task_root: Path,
    claim_if_needed: bool,
    feedback_text: str | None = None,
) -> tuple[str, dict[str, Any], Path, dict[str, Any], str]:
    raw_context = _run_text_command(command=["st", "context", task_id], cwd=task_root)
    task_context = _parse_task_context(raw_context)
    project_root = task_context.get("project_root")

    if (not isinstance(project_root, str) or not project_root) and claim_if_needed:
        _run_text_command(command=["st", "claim", task_id], cwd=task_root)
        raw_context = _run_text_command(command=["st", "context", task_id], cwd=task_root)
        task_context = _parse_task_context(raw_context)
        project_root = task_context.get("project_root")

    if not isinstance(project_root, str) or not project_root:
        raise ValueError(f"task {task_id} has no project root and auto-claim is disabled")

    workdir = Path(project_root).resolve()
    target_paths = _find_target_paths(task_context, workdir=workdir)
    related_tests = _discover_related_tests(workdir=workdir, target_paths=target_paths)
    prompt = _build_prompt_from_task_context(
        task_context,
        project_id=project_id,
        workdir=workdir,
        target_paths=target_paths,
        related_tests=related_tests,
        feedback_text=feedback_text,
    )
    metadata = {
        "task_context": task_context,
        "target_paths": target_paths,
        "related_tests": related_tests,
        "feedback_text": feedback_text,
    }
    return prompt, _task_agents_payload(), workdir, metadata, _task_allowed_tools()


def _build_prompt_from_spec(spec: dict[str, Any]) -> str:
    objective = spec.get("objective")
    response_contract = spec.get("response_contract")
    constraints = _coerce_string_list(spec.get("constraints"))
    paths = _coerce_string_list(spec.get("paths"))
    agent = spec.get("agent") if isinstance(spec.get("agent"), dict) else None

    lines: list[str] = []
    if agent:
        agent_name = agent.get("name") if isinstance(agent.get("name"), str) else "worker"
        lines.append(f"Use exactly one Agent subagent named `{agent_name}`.")
        if len(paths) == 1:
            lines.append(f"Have the subagent read only `{paths[0]}`.")
        elif paths:
            lines.append("Have the subagent read only these paths:")
            lines.extend(f"- `{path}`" for path in paths)
    else:
        if len(paths) == 1:
            lines.append(f"Read only `{paths[0]}`.")
        elif paths:
            lines.append("Read only these paths:")
            lines.extend(f"- `{path}`" for path in paths)

    if isinstance(objective, str) and objective:
        lines.append("")
        lines.append(f"Objective: {objective}")

    if isinstance(response_contract, str) and response_contract:
        lines.append("")
        lines.append(response_contract)

    if constraints:
        lines.append("")
        lines.append("Constraints:")
        lines.extend(f"- {constraint}" for constraint in constraints)

    return "\n".join(lines).strip()


def _build_agents_payload_from_spec(spec: dict[str, Any]) -> dict[str, Any] | None:
    agent = spec.get("agent")
    if not isinstance(agent, dict):
        return None

    name = agent.get("name") if isinstance(agent.get("name"), str) and agent.get("name") else "worker"
    payload: dict[str, Any] = {
        "description": (
            agent.get("description")
            if isinstance(agent.get("description"), str) and agent.get("description")
            else "Scoped analysis worker"
        ),
        "prompt": (
            agent.get("prompt")
            if isinstance(agent.get("prompt"), str) and agent.get("prompt")
            else "Read only the requested files and report back briefly."
        ),
    }

    for key in (
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "mcpServers",
        "hooks",
        "maxTurns",
        "skills",
        "initialPrompt",
        "memory",
        "effort",
        "background",
        "isolation",
    ):
        value = agent.get(key)
        if value is not None:
            payload[key] = value

    return {name: payload}


def _allowed_tools_from_spec(spec: dict[str, Any]) -> str:
    allowed_tools = spec.get("allowed_tools")
    if isinstance(allowed_tools, str) and allowed_tools:
        return allowed_tools
    allowed_tool_list = _coerce_string_list(allowed_tools)
    if allowed_tool_list:
        return ",".join(allowed_tool_list)
    return "Agent" if isinstance(spec.get("agent"), dict) else "Read"


def _emit_status(name: str, value: str | int | float | bool) -> None:
    print(f"{name}={value}", file=sys.stderr, flush=True)


def _build_live_summary(
    *,
    command: list[str],
    artifact_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    metadata_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": state.get("status", "running"),
        "command": command,
        "prompt_chars": state.get("prompt_chars"),
        "artifact_dir": str(artifact_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "metadata_path": str(metadata_path),
        "pid": state.get("pid"),
        "exit_code": state.get("exit_code"),
        "duration_seconds": state.get("duration_seconds"),
        "session_id": state.get("session_id"),
        "transcript_path": state.get("transcript_path"),
        "result": state.get("result"),
        "event_types": state.get("event_types", {}),
        "stdout_lines": state.get("stdout_lines", 0),
        "stderr_lines": state.get("stderr_lines", 0),
        "timed_out": state.get("timed_out", False),
        "transcript_progress": state.get("transcript_progress"),
        "last_progress_at": state.get("last_progress_at"),
    }


def _write_live_summary(
    *,
    metadata_path: Path,
    command: list[str],
    artifact_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    state: dict[str, Any],
) -> None:
    summary = _build_live_summary(
        command=command,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        metadata_path=metadata_path,
        state=state,
    )
    metadata_path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def _process_claude_stdout_line(
    *,
    line: str,
    workdir: Path,
    state: dict[str, Any],
) -> None:
    state["stdout_lines"] = state.get("stdout_lines", 0) + 1
    stripped = line.strip()
    if not stripped:
        return
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return

    payload_type = payload.get("type")
    if isinstance(payload_type, str):
        event_types = state.setdefault("event_types", {})
        event_types[payload_type] = event_types.get(payload_type, 0) + 1

    if payload_type == "system" and payload.get("subtype") == "init":
        session_id = payload.get("session_id") or payload.get("sessionId")
        if isinstance(session_id, str) and session_id and state.get("session_id") != session_id:
            state["session_id"] = session_id
            _emit_status("SESSION_ID", session_id)

    session_id = state.get("session_id")
    if isinstance(session_id, str) and session_id and not state.get("transcript_path"):
        transcript_path = _resolve_transcript_path(workdir, session_id)
        if transcript_path is not None:
            state["transcript_path"] = str(transcript_path)
            _emit_status("TRANSCRIPT_PATH", str(transcript_path))

    if payload_type == "result":
        state["result"] = payload.get("result")


def _extract_transcript_model(payload: dict[str, Any]) -> str | None:
    entry_type = payload.get("type")
    if entry_type == "assistant":
        message = payload.get("message")
        if isinstance(message, dict):
            model = message.get("model")
            if isinstance(model, str) and model:
                return model
    if entry_type == "progress":
        data = payload.get("data")
        if isinstance(data, dict):
            nested = data.get("message")
            if isinstance(nested, dict):
                message = nested.get("message")
                if isinstance(message, dict):
                    model = message.get("model")
                    if isinstance(model, str) and model:
                        return model
    return None


def _read_transcript_progress(transcript_path: str | None) -> dict[str, Any] | None:
    if not transcript_path:
        return None
    path = Path(transcript_path)
    if not path.exists():
        return None

    try:
        raw_lines = path.read_text().splitlines()
        size_bytes = path.stat().st_size
    except OSError:
        return None

    last_payload: dict[str, Any] | None = None
    for line in reversed(raw_lines):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            last_payload = parsed
            break

    progress: dict[str, Any] = {
        "line_count": len(raw_lines),
        "size_bytes": size_bytes,
    }
    if not isinstance(last_payload, dict):
        return progress

    last_type = last_payload.get("type")
    if isinstance(last_type, str) and last_type:
        progress["last_type"] = last_type

    last_model = _extract_transcript_model(last_payload)
    if last_model:
        progress["last_model"] = last_model

    if last_type == "progress":
        data = last_payload.get("data")
        if isinstance(data, dict):
            agent_id = data.get("agentId")
            if isinstance(agent_id, str) and agent_id:
                progress["last_agent_id"] = agent_id
            nested = data.get("message")
            if isinstance(nested, dict):
                nested_type = nested.get("type")
                if isinstance(nested_type, str) and nested_type:
                    progress["last_nested_type"] = nested_type

    return progress


def _refresh_transcript_progress(
    *,
    state: dict[str, Any],
    emit_updates: bool = False,
) -> bool:
    progress = _read_transcript_progress(state.get("transcript_path"))
    if progress is None or progress == state.get("transcript_progress"):
        return False
    state["transcript_progress"] = progress
    state["last_progress_at"] = datetime.now(UTC).isoformat()
    if emit_updates:
        _emit_status(
            "TRANSCRIPT_PROGRESS",
            json.dumps(progress, sort_keys=True, separators=(",", ":")),
        )
    return True


def _process_claude_stderr_line(*, line: str, state: dict[str, Any]) -> None:
    state["stderr_lines"] = state.get("stderr_lines", 0) + 1
    if state["stderr_lines"] <= 5:
        print(line, file=sys.stderr, flush=True)


def _build_claude_command(
    *,
    schema_path: Path | None,
    agents_path: Path | None,
    agents_payload: dict[str, Any] | None,
    model: str,
    effort: str | None,
    append_system_prompt: str | None,
    allowed_tools: str,
    permission_mode: str,
) -> list[str]:
    command = [
        "claude",
        "--print",
        "--verbose",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--permission-mode",
        permission_mode,
        "--model",
        model,
        "--allowedTools",
        allowed_tools,
    ]
    if effort:
        command.extend(["--effort", effort])
    if append_system_prompt:
        command.extend(["--append-system-prompt", append_system_prompt])
    if schema_path is not None:
        command.extend(["--json-schema", str(schema_path)])
    if agents_payload is not None:
        command.extend(["--agents", json.dumps(agents_payload, separators=(",", ":"))])
    elif agents_path is not None:
        command.extend(["--agents", _read_agents_payload(agents_path)])
    return command


def _stream_claude_pipe(
    *,
    stream,
    sink_path: Path,
    state: dict[str, Any],
    state_lock: threading.Lock,
    workdir: Path,
    stream_type: str,
    command: list[str],
    artifact_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    metadata_path: Path,
    project_id: str,
    external_id: str | None,
    batch_task_ids: list[str] | None,
) -> None:
    with sink_path.open("w") as sink:
        for line in iter(stream.readline, ""):
            sink.write(line)
            sink.flush()
            with state_lock:
                if stream_type == "stdout":
                    old_session_id = state.get("session_id")
                    old_transcript_path = state.get("transcript_path")
                    _process_claude_stdout_line(line=line, workdir=workdir, state=state)
                    progress_changed = _refresh_transcript_progress(
                        state=state,
                        emit_updates=True,
                    )
                    metadata_changed = _sync_session_metadata_if_needed(
                        state=state,
                        workdir=workdir,
                        project_id=project_id,
                        external_id=external_id,
                        batch_task_ids=batch_task_ids,
                    )
                    ingest_changed = _sync_transcript_events_if_needed(
                        state=state,
                        workdir=workdir,
                        project_id=project_id,
                        external_id=external_id,
                    )
                    if (
                        state.get("session_id") != old_session_id
                        or state.get("transcript_path") != old_transcript_path
                        or progress_changed
                        or metadata_changed
                        or ingest_changed
                    ):
                        _write_live_summary(
                            metadata_path=metadata_path,
                            command=command,
                            artifact_dir=artifact_dir,
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            state=state,
                        )
                else:
                    _process_claude_stderr_line(line=line.rstrip("\n"), state=state)


def _monitor_transcript_progress(
    *,
    stop_event: threading.Event,
    state: dict[str, Any],
    state_lock: threading.Lock,
    command: list[str],
    artifact_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    metadata_path: Path,
) -> None:
    while not stop_event.wait(0.5):
        with state_lock:
            progress_changed = _refresh_transcript_progress(
                state=state,
                emit_updates=False,
            )
            if not progress_changed:
                continue
            _write_live_summary(
                metadata_path=metadata_path,
                command=command,
                artifact_dir=artifact_dir,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                state=state,
            )


def _run_claude(
    *,
    prompt: str,
    schema_path: Path | None,
    agents_path: Path | None,
    agents_payload: dict[str, Any] | None,
    workdir: Path,
    model: str,
    effort: str | None,
    append_system_prompt: str | None,
    allowed_tools: str,
    permission_mode: str,
    timeout_seconds: int,
    project_id: str,
    external_id: str | None,
    batch_task_ids: list[str] | None = None,
) -> dict[str, Any]:
    artifact_dir = Path(tempfile.mkdtemp(prefix="claude-orchestrated-worker-"))
    stdout_path = artifact_dir / "stdout.jsonl"
    stderr_path = artifact_dir / "stderr.log"
    metadata_path = artifact_dir / "run.json"
    command = _build_claude_command(
        schema_path=schema_path,
        agents_path=agents_path,
        agents_payload=agents_payload,
        model=model,
        effort=effort,
        append_system_prompt=append_system_prompt,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
    )

    started_at = time.time()
    state: dict[str, Any] = {
        "status": "starting",
        "event_types": {},
        "stdout_lines": 0,
        "stderr_lines": 0,
        "timed_out": False,
        "prompt_chars": len(prompt),
    }
    stdout_path.touch()
    stderr_path.touch()
    _write_live_summary(
        metadata_path=metadata_path,
        command=command,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        state=state,
    )
    _emit_status("ARTIFACT_DIR", str(artifact_dir))
    _emit_status("METADATA_PATH", str(metadata_path))

    process = subprocess.Popen(
        command,
        cwd=str(workdir),
        env=_subprocess_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    state["pid"] = process.pid
    state["status"] = "running"
    _emit_status("CLAUDE_PID", process.pid or "unknown")
    _write_live_summary(
        metadata_path=metadata_path,
        command=command,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        state=state,
    )

    assert process.stdout is not None
    assert process.stderr is not None
    assert process.stdin is not None
    state_lock = threading.Lock()
    stdout_thread = threading.Thread(
        target=_stream_claude_pipe,
        kwargs={
            "stream": process.stdout,
            "sink_path": stdout_path,
            "state": state,
            "state_lock": state_lock,
            "workdir": workdir,
            "stream_type": "stdout",
            "command": command,
            "artifact_dir": artifact_dir,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "metadata_path": metadata_path,
            "project_id": project_id,
            "external_id": external_id,
            "batch_task_ids": batch_task_ids,
        },
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_stream_claude_pipe,
        kwargs={
            "stream": process.stderr,
            "sink_path": stderr_path,
            "state": state,
            "state_lock": state_lock,
            "workdir": workdir,
            "stream_type": "stderr",
            "command": command,
            "artifact_dir": artifact_dir,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "metadata_path": metadata_path,
            "project_id": project_id,
            "external_id": external_id,
            "batch_task_ids": batch_task_ids,
        },
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    process.stdin.write(prompt)
    process.stdin.close()
    deadline = time.time() + timeout_seconds
    while True:
        try:
            process.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            with state_lock:
                progress_changed = _refresh_transcript_progress(
                    state=state,
                    emit_updates=False,
                )
                metadata_changed = _sync_session_metadata_if_needed(
                    state=state,
                    workdir=workdir,
                    project_id=project_id,
                    external_id=external_id,
                    batch_task_ids=batch_task_ids,
                )
                ingest_changed = _sync_transcript_events_if_needed(
                    state=state,
                    workdir=workdir,
                    project_id=project_id,
                    external_id=external_id,
                )
                if progress_changed or metadata_changed or ingest_changed:
                    _write_live_summary(
                        metadata_path=metadata_path,
                        command=command,
                        artifact_dir=artifact_dir,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        state=state,
                    )
            if time.time() >= deadline:
                state["timed_out"] = True
                state["status"] = "timed_out"
                _emit_status("TIMEOUT_SECONDS", timeout_seconds)
                process.kill()
                process.wait()
                break

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    with state_lock:
        progress_changed = _refresh_transcript_progress(state=state, emit_updates=False)
        metadata_changed = _sync_session_metadata_if_needed(
            state=state,
            workdir=workdir,
            project_id=project_id,
            external_id=external_id,
            batch_task_ids=batch_task_ids,
        )
        ingest_changed = _sync_transcript_events_if_needed(
            state=state,
            workdir=workdir,
            project_id=project_id,
            external_id=external_id,
        )
        if progress_changed or metadata_changed or ingest_changed:
            _write_live_summary(
                metadata_path=metadata_path,
                command=command,
                artifact_dir=artifact_dir,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                state=state,
            )

    duration_seconds = round(time.time() - started_at, 3)
    state["duration_seconds"] = duration_seconds
    state["exit_code"] = process.returncode
    if state["status"] != "timed_out":
        state["status"] = "completed"
    session_id = state.get("session_id")
    transcript_path_value = state.get("transcript_path")
    if isinstance(session_id, str) and session_id:
        transcript_path = (
            Path(transcript_path_value)
            if isinstance(transcript_path_value, str) and transcript_path_value
            else None
        )
        _run_async(
            _finalize_session_status(
                session_id=session_id,
                project_id=project_id,
                transcript_path=transcript_path,
                workdir=workdir,
                external_id=external_id,
                batch_task_ids=batch_task_ids,
                timed_out=bool(state.get("timed_out")),
                exit_code=process.returncode,
                timeout_seconds=timeout_seconds,
            )
        )

    _write_live_summary(
        metadata_path=metadata_path,
        command=command,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        state=state,
    )
    return _build_live_summary(
        command=command,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        metadata_path=metadata_path,
        state=state,
    )


def _candidate_transcript_paths(workdir: Path, session_id: str) -> list[Path]:
    project_key = "-" + str(workdir.resolve()).lstrip("/").replace("/", "-")
    home = Path.home()
    candidates = [home / ".claude" / "projects" / project_key / f"{session_id}.jsonl"]
    candidates.extend((home / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _resolve_transcript_path(workdir: Path, session_id: str) -> Path | None:
    for path in _candidate_transcript_paths(workdir, session_id):
        if path.exists():
            return path
    return None


async def _ensure_session_metadata(
    *,
    session_id: str,
    project_id: str,
    transcript_path: Path | None,
    workdir: Path,
    external_id: str | None = None,
    batch_task_ids: list[str] | None = None,
) -> None:
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Session
    from app.services.session_ingestion.models import SessionUpsertRequest
    from app.services.session_ingestion.service import upsert_session

    async with async_session() as db:
        existing = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one_or_none()
        if existing is None:
            provider_metadata: dict[str, Any] = {
                "repo_root": str(workdir.resolve()),
            }
            if batch_task_ids:
                provider_metadata["batch_task_ids"] = sorted({task_id for task_id in batch_task_ids if task_id})
            if transcript_path is not None:
                provider_metadata["transcript_path"] = str(transcript_path)
            await upsert_session(
                db,
                SessionUpsertRequest(
                    session_id=session_id,
                    project_id=project_id,
                    provider="claude",
                    model="unknown",
                    session_type="claude_code",
                    external_id=external_id,
                    provider_metadata=provider_metadata,
                ),
            )
            return

        metadata = dict(existing.provider_metadata or {})
        metadata.setdefault("repo_root", str(workdir.resolve()))
        if batch_task_ids:
            metadata["batch_task_ids"] = sorted({task_id for task_id in batch_task_ids if task_id})
        if transcript_path is not None:
            metadata["transcript_path"] = str(transcript_path)
        existing.provider_metadata = metadata
        if external_id and existing.external_id != external_id:
            existing.external_id = external_id
        await db.commit()


def _sync_session_metadata_if_needed(
    *,
    state: dict[str, Any],
    workdir: Path,
    project_id: str,
    external_id: str | None,
    batch_task_ids: list[str] | None = None,
) -> bool:
    session_id = state.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return False
    transcript_path_value = state.get("transcript_path")
    transcript_path = (
        Path(transcript_path_value)
        if isinstance(transcript_path_value, str) and transcript_path_value
        else None
    )
    marker = (session_id, str(transcript_path) if transcript_path is not None else None)
    if state.get("metadata_sync_marker") == marker:
        return False
    _run_async(
        _ensure_session_metadata(
            session_id=session_id,
            project_id=project_id,
            transcript_path=transcript_path,
            workdir=workdir,
            external_id=external_id,
            batch_task_ids=batch_task_ids,
        )
    )
    state["metadata_sync_marker"] = marker
    return True


def _sync_transcript_events_if_needed(
    *,
    state: dict[str, Any],
    workdir: Path,
    project_id: str,
    external_id: str | None,
) -> bool:
    session_id = state.get("session_id")
    transcript_path_value = state.get("transcript_path")
    progress = state.get("transcript_progress")
    if not isinstance(session_id, str) or not session_id:
        return False
    if not isinstance(transcript_path_value, str) or not transcript_path_value:
        return False
    if not isinstance(progress, dict):
        return False
    line_count = progress.get("line_count")
    if not isinstance(line_count, int) or line_count <= 0:
        return False
    marker = (session_id, transcript_path_value, line_count)
    if state.get("live_ingest_marker") == marker:
        return False
    ingest = _run_async(
        _ingest_transcript(
            session_id=session_id,
            project_id=project_id,
            transcript_path=Path(transcript_path_value),
            workdir=workdir,
            external_id=external_id,
            checkpoint=state.get("live_ingest_checkpoint"),
        )
    )
    state["live_ingest_checkpoint"] = ingest.get("next_checkpoint")
    state["live_ingest_marker"] = marker
    state["live_ingest"] = {
        "events_appended": ingest.get("events_appended"),
        "events_skipped": ingest.get("events_skipped"),
        "last_turn": ingest.get("last_turn"),
        "last_sequence": ingest.get("last_sequence"),
        "next_checkpoint": ingest.get("next_checkpoint"),
    }
    return True


async def _ingest_transcript(
    *,
    session_id: str,
    project_id: str,
    transcript_path: Path,
    workdir: Path,
    external_id: str | None = None,
    batch_task_ids: list[str] | None = None,
    checkpoint: str | None = None,
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Session
    from app.services.session_ingestion.models import TranscriptIngestRequest
    from app.services.session_ingestion.service import ingest_transcript_events

    await _ensure_session_metadata(
        session_id=session_id,
        project_id=project_id,
        transcript_path=transcript_path,
        workdir=workdir,
        external_id=external_id,
        batch_task_ids=batch_task_ids,
    )
    async with async_session() as db:
        ingest_result = await ingest_transcript_events(
            db,
            session_id,
            TranscriptIngestRequest(
                provider="claude",
                transcript_path=str(transcript_path),
                checkpoint=checkpoint,
            ),
        )
    async with async_session() as db:
        session = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one()
    return {
        "events_appended": ingest_result.events_appended,
        "events_skipped": ingest_result.events_skipped,
        "last_turn": ingest_result.last_turn,
        "last_sequence": ingest_result.last_sequence,
        "next_checkpoint": ingest_result.next_checkpoint,
        "session": {
            "id": session.id,
            "project_id": session.project_id,
            "model": session.model,
            "models_used": session.models_used,
            "observed_read_paths": session.observed_read_paths,
            "observed_write_paths": session.observed_write_paths,
            "scope_confidence": session.scope_confidence,
        },
    }


async def _finalize_session_status(
    *,
    session_id: str,
    project_id: str,
    transcript_path: Path | None,
    workdir: Path,
    external_id: str | None,
    batch_task_ids: list[str] | None = None,
    timed_out: bool,
    exit_code: int | None,
    timeout_seconds: int,
) -> None:
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Session
    from app.services.session_live_activity import (
        mark_session_completed,
        mark_session_terminal_state,
    )

    await _ensure_session_metadata(
        session_id=session_id,
        project_id=project_id,
        transcript_path=transcript_path,
        workdir=workdir,
        external_id=external_id,
        batch_task_ids=batch_task_ids,
    )
    async with async_session() as db:
        session = (
            await db.execute(select(Session).where(Session.id == session_id).limit(1))
        ).scalar_one_or_none()
        if session is None:
            return
        if timed_out:
            session.status = "failed"
            session.health_detail = "timed_out"
            mark_session_terminal_state(
                session,
                phase="failed",
                status="failed",
                summary=f"Claude worker timed out after {timeout_seconds}s",
                termination_reason="timeout",
            )
        elif exit_code == 0:
            mark_session_completed(
                session,
                summary="Claude worker completed",
                termination_reason="process_exit_0",
            )
        else:
            session.status = "failed"
            session.health_detail = "failed"
            mark_session_terminal_state(
                session,
                phase="failed",
                status="failed",
                summary=f"Claude worker exited with code {exit_code}",
                termination_reason=f"process_exit_{exit_code}",
            )
        await db.commit()


def main() -> int:
    args = _parse_args()
    spec = _read_json_object(args.spec_file) if args.spec_file else None
    task_metadata: dict[str, Any] | None = None
    task_allowed_tools: str | None = None
    if args.task_id:
        prompt, agents_payload, workdir, task_metadata, task_allowed_tools = _load_task_contract(
            task_id=args.task_id,
            project_id=args.project_id,
            task_root=Path(args.task_root).resolve(),
            claim_if_needed=args.claim_if_needed,
            feedback_text=args.feedback_text,
        )
    else:
        prompt = _build_prompt_from_spec(spec) if spec is not None else _read_text(args.prompt_file)
        agents_payload = _build_agents_payload_from_spec(spec) if spec is not None else None
        workdir = Path(args.workdir).resolve()
    prompt = _apply_skills_to_prompt(prompt, args.skill)
    schema_path = Path(args.schema_file).resolve() if args.schema_file else None
    agents_path = Path(args.agents_file).resolve() if args.agents_file else None
    allowed_tools = (
        task_allowed_tools
        if task_allowed_tools is not None
        else _allowed_tools_from_spec(spec) if spec is not None else args.allowed_tools
    )

    run_summary = _run_claude(
        prompt=prompt,
        schema_path=schema_path,
        agents_path=agents_path,
        agents_payload=agents_payload,
        workdir=workdir,
        model=args.model,
        effort=args.effort,
        append_system_prompt=args.append_system_prompt,
        allowed_tools=allowed_tools,
        permission_mode=args.permission_mode,
        timeout_seconds=args.timeout_seconds,
        project_id=args.project_id,
        external_id=args.task_id,
        batch_task_ids=args.batch_task_id,
    )

    output: dict[str, Any] = {
        "run": run_summary,
    }
    if task_metadata is not None:
        output["task"] = task_metadata
    session_id = run_summary.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        output["error"] = "Claude run did not emit a session_id"
        print(json.dumps(output, indent=2))
        return 1

    transcript_path = _resolve_transcript_path(workdir, session_id)
    output["transcript_path"] = str(transcript_path) if transcript_path else None

    if transcript_path is not None and not args.skip_ingest:
        output["ingest"] = _run_async(
            _ingest_transcript(
                session_id=session_id,
                project_id=args.project_id,
                transcript_path=transcript_path,
                workdir=workdir,
                external_id=args.task_id,
                batch_task_ids=args.batch_task_id,
            )
        )

    print(json.dumps(output, indent=2))
    return 0 if run_summary["exit_code"] == 0 else run_summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
