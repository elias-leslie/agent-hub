from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_resilience import MemoryFailureDetails
from app.services.memory.failure_reporting import (
    MemoryFailureReport,
    report_memory_failure,
    write_memory_failure_journal,
)


def _sample_report() -> MemoryFailureReport:
    return MemoryFailureReport(
        failure=MemoryFailureDetails(
            operation="progressive-context",
            attempts=3,
            error_type="RuntimeError",
            error_message="neo4j restart in progress",
            latency_ms=912,
        ),
        consumer_profile="codex_startup",
        project_id="summitflow",
        session_id="session-123",
        external_id="task-456",
        current_branch="main",
        source="test",
    )


def test_write_memory_failure_journal_appends_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    path = write_memory_failure_journal(_sample_report())

    assert path == tmp_path / "agent-hub" / "memory_failures.jsonl"
    entries = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 1
    payload = json.loads(entries[0])
    assert payload["project_id"] == "summitflow"
    assert payload["failure"]["operation"] == "progressive-context"
    assert payload["failure"]["attempts"] == 3


@pytest.mark.asyncio
async def test_report_memory_failure_records_journal_and_session_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    with patch(
        "app.services.memory.failure_reporting._store_failure_session_event",
        new=AsyncMock(return_value=(True, None)),
    ) as mock_store:
        result = await report_memory_failure(_sample_report())

    assert mock_store.await_count == 1
    assert result.session_event_recorded is True
    assert result.session_event_error is None
    assert Path(result.journal_path).exists()


@pytest.mark.asyncio
async def test_report_memory_failure_tolerates_session_event_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    with patch(
        "app.services.memory.failure_reporting._store_failure_session_event",
        new=AsyncMock(side_effect=RuntimeError("db offline")),
    ):
        result = await report_memory_failure(_sample_report())

    assert result.session_event_recorded is False
    assert "db offline" in (result.session_event_error or "")
    assert Path(result.journal_path).exists()
