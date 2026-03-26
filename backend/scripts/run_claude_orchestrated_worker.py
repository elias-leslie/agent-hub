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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"

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
    parser.add_argument("--prompt-file", required=True, help="Markdown/text prompt file for Claude")
    parser.add_argument("--schema-file", help="Optional JSON schema file for StructuredOutput")
    parser.add_argument("--agents-file", help="Optional Claude agents JSON file")
    parser.add_argument("--project-id", default="agent-hub", help="Agent Hub project id")
    parser.add_argument("--workdir", default=str(ROOT), help="Working directory for the Claude run")
    parser.add_argument("--model", default="sonnet", help="Claude model alias")
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
        "--skip-ingest",
        action="store_true",
        help="Skip Agent Hub transcript ingestion and only emit raw artifacts",
    )
    return parser.parse_args()


def _read_text(path_str: str) -> str:
    return Path(path_str).read_text().strip()


def _read_agents_payload(path: Path) -> str:
    raw = path.read_text().strip()
    try:
        return json.dumps(json.loads(raw), separators=(",", ":"))
    except json.JSONDecodeError:
        return raw


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


def _process_claude_stderr_line(*, line: str, state: dict[str, Any]) -> None:
    state["stderr_lines"] = state.get("stderr_lines", 0) + 1
    if state["stderr_lines"] <= 5:
        print(line, file=sys.stderr, flush=True)


def _build_claude_command(
    *,
    schema_path: Path | None,
    agents_path: Path | None,
    model: str,
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
    if schema_path is not None:
        command.extend(["--json-schema", str(schema_path)])
    if agents_path is not None:
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
                    if (
                        state.get("session_id") != old_session_id
                        or state.get("transcript_path") != old_transcript_path
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


def _run_claude(
    *,
    prompt: str,
    schema_path: Path | None,
    agents_path: Path | None,
    workdir: Path,
    model: str,
    allowed_tools: str,
    permission_mode: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    artifact_dir = Path(tempfile.mkdtemp(prefix="claude-orchestrated-worker-"))
    stdout_path = artifact_dir / "stdout.jsonl"
    stderr_path = artifact_dir / "stderr.log"
    metadata_path = artifact_dir / "run.json"
    command = _build_claude_command(
        schema_path=schema_path,
        agents_path=agents_path,
        model=model,
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
        },
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        state["timed_out"] = True
        state["status"] = "timed_out"
        _emit_status("TIMEOUT_SECONDS", timeout_seconds)
        process.kill()
        process.wait()

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)

    duration_seconds = round(time.time() - started_at, 3)
    state["duration_seconds"] = duration_seconds
    state["exit_code"] = process.returncode
    if state["status"] != "timed_out":
        state["status"] = "completed"

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
    transcript_path: Path,
    workdir: Path,
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
            await upsert_session(
                db,
                SessionUpsertRequest(
                    session_id=session_id,
                    project_id=project_id,
                    provider="claude",
                    model="unknown",
                    session_type="claude_code",
                    provider_metadata={
                        "transcript_path": str(transcript_path),
                        "repo_root": str(workdir.resolve()),
                    },
                ),
            )
            return

        metadata = dict(existing.provider_metadata or {})
        metadata["transcript_path"] = str(transcript_path)
        metadata.setdefault("repo_root", str(workdir.resolve()))
        existing.provider_metadata = metadata
        await db.commit()


async def _ingest_transcript(
    *,
    session_id: str,
    project_id: str,
    transcript_path: Path,
    workdir: Path,
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
    )
    async with async_session() as db:
        ingest_result = await ingest_transcript_events(
            db,
            session_id,
            TranscriptIngestRequest(provider="claude", transcript_path=str(transcript_path)),
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


def main() -> int:
    args = _parse_args()
    prompt = _read_text(args.prompt_file)
    schema_path = Path(args.schema_file).resolve() if args.schema_file else None
    agents_path = Path(args.agents_file).resolve() if args.agents_file else None
    workdir = Path(args.workdir).resolve()

    run_summary = _run_claude(
        prompt=prompt,
        schema_path=schema_path,
        agents_path=agents_path,
        workdir=workdir,
        model=args.model,
        allowed_tools=args.allowed_tools,
        permission_mode=args.permission_mode,
        timeout_seconds=args.timeout_seconds,
    )

    output: dict[str, Any] = {
        "run": run_summary,
    }
    session_id = run_summary.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        output["error"] = "Claude run did not emit a session_id"
        print(json.dumps(output, indent=2))
        return 1

    transcript_path = _resolve_transcript_path(workdir, session_id)
    output["transcript_path"] = str(transcript_path) if transcript_path else None

    if transcript_path is not None and not args.skip_ingest:
        output["ingest"] = asyncio.run(
            _ingest_transcript(
                session_id=session_id,
                project_id=args.project_id,
                transcript_path=transcript_path,
                workdir=workdir,
            )
        )

    print(json.dumps(output, indent=2))
    return 0 if run_summary["exit_code"] == 0 else run_summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
