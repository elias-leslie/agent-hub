from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.scripts.send_jenny_telegram_status_report import (
    build_complete_command,
    build_prompt,
    deliver_report,
    extract_report_text,
    persona_status_report_skip_reason,
)


def test_build_prompt_mentions_live_checks_and_sections() -> None:
    prompt = build_prompt()

    assert "st pulse" in prompt
    assert "st sessions ownership" in prompt
    assert "Sections required" in prompt


def test_build_complete_command_targets_persona_and_executes_tools() -> None:
    command = build_complete_command("report prompt")

    assert command[:3] == [
        "st",
        "complete",
        "-a",
    ]
    assert "persona" in command
    assert "agent-hub" in command
    assert "-x" in command
    assert "--skip-cache" in command
    assert "--raw" in command
    assert command[-2:] == ["--message", "report prompt"]


def test_extract_report_text_returns_trimmed_content() -> None:
    raw = json.dumps({"content": "  Jenny report  "})

    assert extract_report_text(raw) == "Jenny report"


def test_extract_report_text_rejects_empty_content() -> None:
    with pytest.raises(RuntimeError, match="empty content"):
        extract_report_text(json.dumps({"content": "   "}))


def test_persona_status_report_skip_reason_respects_disabled_heartbeat() -> None:
    persona = SimpleNamespace(execution_state="active", heartbeat_interval_minutes=0)

    assert (
        persona_status_report_skip_reason(persona, heartbeat_schedule_enabled=True)
        == "persona_heartbeat_disabled"
    )


def test_persona_status_report_skip_reason_respects_disabled_schedule() -> None:
    persona = SimpleNamespace(execution_state="active", heartbeat_interval_minutes=60)

    assert (
        persona_status_report_skip_reason(persona, heartbeat_schedule_enabled=False)
        == "persona_heartbeat_schedule_disabled"
    )


def test_persona_status_report_skip_reason_allows_active_heartbeat() -> None:
    persona = SimpleNamespace(execution_state="active", heartbeat_interval_minutes=60)

    assert persona_status_report_skip_reason(persona, heartbeat_schedule_enabled=True) is None


@pytest.mark.asyncio
async def test_deliver_report_dry_run_prints_body(capsys: pytest.CaptureFixture[str]) -> None:
    sent = await deliver_report(title="Jenny", body="Status body", dry_run=True)

    captured = capsys.readouterr()
    assert sent == 0
    assert "Status body" in captured.out
