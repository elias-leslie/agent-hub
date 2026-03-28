"""Shared reporting for memory/context injection failures."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.db import async_session
from app.models import Session, SessionEventType
from app.services.event_storage import store_event

from .context_resilience import MemoryFailureDetails


@dataclass(slots=True)
class MemoryFailureReport:
    """Normalized report payload for a memory/context injection failure."""

    failure: MemoryFailureDetails
    consumer_profile: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    external_id: str | None = None
    current_branch: str | None = None
    provider: str | None = None
    model: str | None = None
    session_type: str | None = None
    cwd: str | None = None
    repo_root: str | None = None
    source: str | None = None


@dataclass(slots=True)
class MemoryFailureReportResult:
    """Outcome of recording a memory failure."""

    journal_path: str
    session_event_recorded: bool
    session_event_error: str | None = None


def _default_failure_journal_path() -> Path:
    state_home = os.getenv("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "agent-hub" / "memory_failures.jsonl"


def _serialize_report(report: MemoryFailureReport) -> dict[str, object]:
    payload = {
        "reported_at": datetime.now(UTC).isoformat(),
        "hostname": socket.gethostname(),
        "source": report.source or "unknown",
        "consumer_profile": report.consumer_profile,
        "project_id": report.project_id,
        "session_id": report.session_id,
        "external_id": report.external_id,
        "current_branch": report.current_branch,
        "provider": report.provider,
        "model": report.model,
        "session_type": report.session_type,
        "cwd": report.cwd,
        "repo_root": report.repo_root,
        "failure": asdict(report.failure),
    }
    return {key: value for key, value in payload.items() if value is not None}


def write_memory_failure_journal(report: MemoryFailureReport) -> Path:
    """Append a durable local JSONL record for a memory failure."""
    path = _default_failure_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_serialize_report(report), sort_keys=True))
        handle.write("\n")
    return path


async def _store_failure_session_event(report: MemoryFailureReport) -> tuple[bool, str | None]:
    if not report.session_id:
        return False, "session_id missing"

    async with async_session() as db:
        session = await db.get(Session, report.session_id)
        if session is None:
            return False, f"session not found: {report.session_id}"

        content = (
            "Memory context injection failed: "
            f"{report.failure.error_type}: {report.failure.error_message}"
        )
        await store_event(
            db=db,
            session_id=report.session_id,
            event_type=SessionEventType.ERROR,
            content=content,
            tool_name="memory_context",
            tool_output={
                "operation": report.failure.operation,
                "attempts": report.failure.attempts,
                "error_type": report.failure.error_type,
                "error_message": report.failure.error_message,
                "latency_ms": report.failure.latency_ms,
                "consumer_profile": report.consumer_profile,
                "project_id": report.project_id,
                "external_id": report.external_id,
                "current_branch": report.current_branch,
                "source": report.source,
            },
            session=session,
        )
        await db.commit()
    return True, None


async def report_memory_failure(report: MemoryFailureReport) -> MemoryFailureReportResult:
    """Write a durable journal entry and best-effort session event for a failure."""
    try:
        journal_path = write_memory_failure_journal(report)
    except Exception as exc:  # pragma: no cover - defensive path
        journal_path = _default_failure_journal_path()
        session_error = f"journal write failed: {type(exc).__name__}: {exc}"
        return MemoryFailureReportResult(
            journal_path=str(journal_path),
            session_event_recorded=False,
            session_event_error=session_error,
        )

    try:
        recorded, session_error = await _store_failure_session_event(report)
    except Exception as exc:  # pragma: no cover - defensive path
        recorded = False
        session_error = f"session event write failed: {type(exc).__name__}: {exc}"
    return MemoryFailureReportResult(
        journal_path=str(journal_path),
        session_event_recorded=recorded,
        session_event_error=session_error,
    )
