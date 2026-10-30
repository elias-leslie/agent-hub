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


def test_retirement_cli_failure_receipt_is_content_free(monkeypatch, capsys):
    from unittest.mock import AsyncMock

    from app.cli import runtime_context
    from app.services.session_ingestion import pi_sync

    monkeypatch.setattr(pi_sync, "retire_pi_sessions", AsyncMock(side_effect=ValueError("private detail")))
    assert runtime_context.main(["retire-pi", "--aico-session", "aico-widget-12345678"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Pi retirement sync unavailable\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["codex", "claude_code"])
@pytest.mark.parametrize("child", [False, True])
async def test_native_work_role_binding_uses_canonical_upsert(monkeypatch, surface, child):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.cli import runtime_context
    from app.services import runtime_context as service_context
    from app.services.session_ingestion import native_work_role

    sid = "00000000-0000-4000-8000-000000000001"
    role = {"id": "implementation", "source": "tether:root:fixture"}
    existing = SimpleNamespace(provider="codex" if surface == "codex" else "anthropic",
        model="observed/model", session_type="agent", parent_session_id="parent" if child else None)
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)
    scope = AsyncMock()
    scope.__aenter__.return_value = db
    monkeypatch.setattr(runtime_context, "async_session", MagicMock(return_value=scope))
    monkeypatch.setattr(service_context, "_resolve_canonical_project_id", AsyncMock(return_value="fixture"))
    upsert = AsyncMock()
    monkeypatch.setattr(native_work_role, "upsert_session", upsert)
    args = _build_parser().parse_args(["bind-native-work-role", "--surface", surface,
        "--session", sid, "--cwd", "/fixture", "--work-role-json", json.dumps(role)])
    await runtime_context._bind_native_work_role(args)
    if child:
        upsert.assert_not_awaited()
    else:
        assert upsert.await_args is not None
        request = upsert.await_args.args[1]
        assert request.session_id == sid
        assert request.model == "observed/model"
        assert request.provider_metadata["work_role"] == role


def test_native_work_role_failure_is_content_free(monkeypatch, capsys):
    from unittest.mock import AsyncMock

    from app.cli import runtime_context

    monkeypatch.setattr(runtime_context, "_bind_native_work_role", AsyncMock(side_effect=ValueError("private detail")))
    assert runtime_context.main(["bind-native-work-role", "--surface", "codex", "--session", "invalid",
        "--cwd", "/fixture", "--work-role-json", "{} "]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Native session work role registration unavailable\n"
