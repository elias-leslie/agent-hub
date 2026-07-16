"""Tests for the stable canonical context CLI contract."""

from app.cli.runtime_context import _build_parser, _parse_metadata


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
