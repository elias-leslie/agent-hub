"""The trusted local owner surface does not expose collector promotion or raw errors."""

from pathlib import Path

from typer.testing import CliRunner

from agent_hub_st import native_sessions

runner = CliRunner()


def test_projection_requires_known_mode_and_invokes_owner_domain(monkeypatch):
    calls = []
    monkeypatch.setattr(native_sessions, "_run_owner_action", lambda action, **args: calls.append((action, args)) or {"promotion_state": args["mode"]})
    result = runner.invoke(native_sessions.app, ["projection", "own-thread", "--mode", "shadow"])
    assert result.exit_code == 0 and calls == [("projection", {"session_id": "own-thread", "mode": "shadow"})]
    rejected = runner.invoke(native_sessions.app, ["projection", "own-thread", "--mode", "unsafe"])
    assert rejected.exit_code != 0 and len(calls) == 1


def test_database_errors_never_print_bound_observations(monkeypatch):
    def fail(*args, **kwargs):
        raise Exception("private prompt and approval contents")
    monkeypatch.setattr(native_sessions, "_run_owner_action", fail)
    result = runner.invoke(native_sessions.app, ["status", "own-thread"])
    assert result.exit_code == 1 and "private prompt" not in result.output
    assert "transaction rolled back" in result.output


def test_raw_retention_has_no_implicit_cutoff_or_apply(monkeypatch):
    calls = []
    monkeypatch.setattr(native_sessions, "_run_owner_action", lambda action, **args: calls.append((action, args)) or {"applied": args["apply"]})
    assert runner.invoke(native_sessions.app, ["prune-raw", "--project", "agent-hub"]).exit_code != 0
    result = runner.invoke(native_sessions.app, ["prune-raw", "--project", "agent-hub", "--older-than", "2026-01-01T00:00:00Z"])
    assert result.exit_code == 0 and calls[0][1]["apply"] is False


def test_fixed_owner_root_ignores_current_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert native_sessions._backend_root() == Path("/srv/workspaces/projects/agent-hub/backend")
