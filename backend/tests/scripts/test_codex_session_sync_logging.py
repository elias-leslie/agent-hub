from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "codex-session-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_session_sync_logging", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    # Never ask the live Agent Hub for settings from a unit test.
    module.fetch_close_settings = lambda *_args: {}  # type: ignore[attr-defined]
    return module


@pytest.mark.parametrize("level", ["WARN", "ERROR"])
def test_diagnostics_reach_stderr_without_touching_legacy_log(
    monkeypatch, tmp_path, capsys, level,
) -> None:
    module = _load_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy_log = tmp_path / ".codex" / "session-integrations" / "codex-session-sync.log"
    legacy_log.parent.mkdir(parents=True)
    legacy_log.write_bytes(b"retained diagnostic history\n")

    module.log(f"[{level}] diagnostic")

    captured = capsys.readouterr()
    assert f"[{level}] diagnostic" in captured.err
    assert captured.out == ""
    assert legacy_log.read_bytes() == b"retained diagnostic history\n"
    assert list(legacy_log.parent.iterdir()) == [legacy_log]


def test_info_reaches_stdout_without_creating_codex_directory(monkeypatch, tmp_path, capsys):
    module = _load_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    module.log("[INFO] diagnostic summary")

    captured = capsys.readouterr()
    assert "[INFO] diagnostic summary" in captured.out
    assert captured.err == ""
    assert not (tmp_path / ".codex").exists()


@pytest.mark.parametrize("verbose", [False, True])
def test_sync_reports_summary_and_keeps_per_session_details_opt_in(monkeypatch, capsys, verbose):
    module = _load_module()
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")

    def fake_run_sync(args, **kwargs):
        assert args.verbose is True
        kwargs["log_fn"]("[INFO] Synced session=one project=summitflow")
        kwargs["log_fn"]("[INFO] Synced session=two project=summitflow")
        kwargs["log_fn"]("[WARN] skipped conflicting session")
        return 0

    monkeypatch.setattr(module, "run_sync", fake_run_sync)

    assert module.main(["--scan"] + (["--verbose"] if verbose else [])) == 0

    captured = capsys.readouterr()
    assert "Codex sync completed status=0 synced=2 warnings=1" in captured.out
    assert ("Synced session=one" in captured.out) is verbose
    assert ("Synced session=two" in captured.out) is verbose
    assert captured.err.count("skipped conflicting session") == 1


@pytest.mark.parametrize("exit_code", [0, 2])
def test_empty_or_failed_scan_has_visible_status_summary(monkeypatch, capsys, exit_code):
    module = _load_module()
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")
    monkeypatch.setattr(module, "run_sync", lambda *_, **__: exit_code)

    assert module.main(["--scan"]) == exit_code

    captured = capsys.readouterr()
    output = captured.out if exit_code == 0 else captured.err
    assert f"Codex sync completed status={exit_code} synced=0 warnings=0" in output


def test_missing_credentials_warns_once_to_direct_cli(monkeypatch, capsys):
    module = _load_module()
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")
    monkeypatch.setattr(module, "run_sync", lambda *_, **__: pytest.fail("unexpected sync"))

    assert module.main(["--scan"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("Missing SUMMITFLOW_CLIENT_ID") == 1


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Unit tests never read the owner's real ~/.codex or ~/.env.local."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
