"""Tests for the stable canonical context CLI contract."""

import pytest

from app.cli.runtime_context import _build_parser, _parse_metadata


def test_status_reports_failed_assembly(monkeypatch, capsys) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.cli import runtime_context

    monkeypatch.setattr(runtime_context, "_render", AsyncMock(return_value=SimpleNamespace(
        status="failed", consumer_profile="agent_startup", project_id="agent-hub",
        blocks=[], total_tokens=0,
    )))
    assert runtime_context.main(["status"]) == 2
    assert "runtime_context=FAILED" in capsys.readouterr().out


def test_deliver_parser_accepts_shared_tui_contract_flags() -> None:
    args = _build_parser().parse_args(
        [
            "deliver",
            "--surface",
            "codex",
            "--cwd",
            "/srv/workspaces/projects/agent-hub",
            "--project",
            "agent-hub",
            "--session",
            "session-1",
            "--task",
            "Audit context",
            "--query",
            "Audit context",
            "--branch",
            "main",
            "--provider",
            "openai",
            "--model",
            "gpt-5",
            "--task-type",
            "implementation",
            "--phase",
            "startup",
            "--profile",
            "agent_startup",
            "--hook-event",
            "SessionStart",
            "--subagent-id",
            "agent-1",
            "--metadata",
            "source=resume",
            "--format",
            "json",
        ]
    )

    assert args.command == "deliver"
    assert args.surface == "codex"
    assert args.consumer_profile == "agent_startup"
    assert args.session == "session-1"
    assert args.query == "Audit context"
    assert args.format == "json"
    assert _parse_metadata(args.metadata) == {"source": "resume"}


def test_consumer_profile_legacy_alias_remains_supported() -> None:
    args = _build_parser().parse_args(
        ["deliver", "--surface", "pi", "--consumer-profile", "agent_startup"]
    )

    assert args.consumer_profile == "agent_startup"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["on", "off"])
async def test_optional_context_mode_maps_existing_selectors_and_preserves_required_policy(monkeypatch, mode) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.cli import runtime_context

    build = AsyncMock()
    monkeypatch.setattr(runtime_context, "build_canonical_context_delivery", build)
    monkeypatch.setattr(runtime_context, "async_session", MagicMock(return_value=AsyncMock()))
    args = _build_parser().parse_args(["deliver", "--surface", "pi", "--optional-context", mode])
    await runtime_context._deliver(args)
    request = build.call_args.args[1]
    assert request.include_global and request.include_prompts and request.include_memories
    assert request.include_mandates and request.include_guardrails
    for field in ("include_references", "include_reference_index", "include_project_index",
                  "include_tool_capabilities", "include_continuity"):
        assert getattr(request, field) is (mode == "on")


def test_pi_sync_parser_and_failure_receipt(monkeypatch, capsys) -> None:
    from unittest.mock import AsyncMock

    from app.cli import runtime_context

    arguments = ["sync-pi", "--session", "native", "--transcript", "/fixture/pi.jsonl",
                 "--cwd", "/fixture", "--provider", "openai-codex", "--model", "gpt-6.1-sol"]
    assert _build_parser().parse_args(arguments).project is None
    monkeypatch.setattr(runtime_context, "_sync_pi", AsyncMock(side_effect=ValueError("private detail")))
    assert runtime_context.main(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Pi session sync unavailable\n"
