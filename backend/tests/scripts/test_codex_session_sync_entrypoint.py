from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "codex-session-sync.py"



def _load_module():
    spec = importlib.util.spec_from_file_location("codex_session_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    # Never ask the live Agent Hub for settings from a unit test.
    module.fetch_close_settings = lambda *_args: {}  # type: ignore[attr-defined]
    return module


def test_entrypoint_runs_with_registered_client_id_and_no_secret(monkeypatch) -> None:
    module = _load_module()
    captured = {}
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")

    def fake_run_sync(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(module, "run_sync", fake_run_sync)

    assert module.main(["--scan"]) == 0
    assert captured["kwargs"]["client_id"] == "summitflow"
    assert "client_secret" not in captured["kwargs"]


def test_entrypoint_skips_only_when_registered_client_id_is_missing(monkeypatch) -> None:
    module = _load_module()
    messages: list[str] = []
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")
    monkeypatch.setattr(module, "log", messages.append)

    assert module.main(["--scan"]) == 0
    assert messages == ["[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync"]


def test_entrypoint_requires_complete_project_binding_arguments(monkeypatch) -> None:
    module = _load_module()
    messages: list[str] = []
    monkeypatch.setattr(module, "log", messages.append)

    assert module.main(["--bind-session", "thread-1"]) == 2
    assert messages == [
        "[WARN] Binding requires --bind-session, --bind-project, and --project-root"
    ]


def test_binding_requires_current_thread_and_credentials(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")
    monkeypatch.setattr(module, "resolve_current_transcript", lambda: SimpleNamespace(session_id="thread-1"))

    args = [
        "--bind-session",
        "thread-1",
        "--bind-project",
        "rootfall",
        "--project-root",
        "/srv/workspaces/projects/rootfall",
    ]
    assert module.main(args) == 2
    assert "Missing SUMMITFLOW_CLIENT_ID" in capsys.readouterr().err

    args[1] = "another-thread"
    assert module.main(args) == 2
    assert "must match the validated current native Codex thread ID" in capsys.readouterr().err


def test_binding_prefers_native_session_id_over_inherited_thread_id(
    monkeypatch,
) -> None:
    module = _load_module()
    captured = {}
    monkeypatch.setenv("CODEX_THREAD_ID", "stale-parent-thread")
    monkeypatch.setenv("CODEX_SESSION_ID", "native-session")
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")
    monkeypatch.setattr(module, "resolve_current_transcript", lambda: SimpleNamespace(session_id="native-session"))

    def fake_run_sync(args, **kwargs):
        captured["session_id"] = args.bind_session
        return 0

    monkeypatch.setattr(module, "run_sync", fake_run_sync)
    result = module.main([
        "--bind-session", "native-session",
        "--bind-project", "neri",
        "--project-root", "/srv/workspaces/projects/neri",
    ])

    assert result == 0
    assert captured["session_id"] == "native-session"


def test_binding_warnings_are_visible_to_cli_subprocess(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")
    monkeypatch.setattr(module, "resolve_current_transcript", lambda: SimpleNamespace(session_id="thread-1"))

    def fake_run_sync(_args, **kwargs):
        kwargs["log_fn"]("[WARN] simulated binding conflict")
        return 2

    monkeypatch.setattr(module, "run_sync", fake_run_sync)
    result = module.main(
        [
            "--bind-session",
            "thread-1",
            "--bind-project",
            "rootfall",
            "--project-root",
            "/srv/workspaces/projects/rootfall",
        ]
    )

    assert result == 2
    assert "simulated binding conflict" in capsys.readouterr().err


def test_binding_native_validation_failure_never_loads_credentials_or_mutates(monkeypatch, capsys):
    module = _load_module()
    calls = []
    def rejected():
        raise ValueError("contradictory native provenance")
    monkeypatch.setattr(module, "resolve_current_transcript", rejected)
    monkeypatch.setattr(module, "load_env_credentials", lambda: calls.append("credentials"))
    monkeypatch.setattr(module, "run_sync", lambda *_, **__: calls.append("mutation"))
    assert module.main(["--bind-session", "unrelated", "--bind-project", "neri", "--project-root", "/srv/workspaces/projects/neri"]) == 2
    assert calls == []
    assert "contradictory native provenance" in capsys.readouterr().err


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Unit tests never read the owner's real ~/.codex or ~/.env.local."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))


def _args(module, *argv: str):
    return module.parse_args(list(argv))


def test_scan_window_comes_from_settings_unless_given(monkeypatch) -> None:
    module = _load_module()
    args = _args(module, "--scan")
    assert module.apply_close_settings(args, {"codex_scan_hours": 6}) == []
    assert args.recent_hours == 6

    args = _args(module, "--scan", "--recent-hours", "48")
    module.apply_close_settings(args, {"codex_scan_hours": 6})
    assert args.recent_hours == 48


def test_inactive_close_follows_the_setting(monkeypatch) -> None:
    module = _load_module()
    args = _args(module, "--scan", "--close-inactive")
    notes = module.apply_close_settings(args, {"codex_close_inactive_enabled": False})
    assert args.close_inactive is False
    assert notes == ["[INFO] Closing inactive Codex sessions is switched off in session close settings"]

    args = _args(module, "--scan", "--close-inactive")
    module.apply_close_settings(args, {"codex_close_inactive_enabled": True})
    assert args.close_inactive is True


def test_unreachable_settings_keep_defaults_and_warn(monkeypatch) -> None:
    module = _load_module()
    args = _args(module, "--scan", "--close-inactive")
    notes = module.apply_close_settings(args, None)
    assert args.recent_hours == module.DEFAULT_SCAN_HOURS
    assert args.close_inactive is True
    assert notes == ["[WARN] Session close settings unavailable; using defaults"]
