"""Tests for the manifest-backed tool capability context adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.memory import tool_capability_context as tcc


def _stub_run(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _clear_cache() -> None:
    tcc._manifest_inject.cache_clear()


def test_format_tool_capability_context_wraps_manifest_body() -> None:
    _clear_cache()
    inject_body = "mandates:\n  st.pulse:\n    cmd: st pulse --gate\n    when: session start"
    with patch.object(tcc, "run_process", return_value=_stub_run(stdout=inject_body)):
        rendered = tcc.format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id="agent-hub",
            bash_available=True,
        )

    assert rendered.startswith("<tool-usage>\n")
    assert rendered.endswith("\n</tool-usage>")
    assert "st.pulse" in rendered
    assert "st pulse --gate" in rendered


def test_format_tool_capability_context_invokes_manifest_with_filters() -> None:
    _clear_cache()
    with patch.object(tcc, "run_process", return_value=_stub_run(stdout="mandates: {}")) as mocked:
        tcc.format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="devops",
            project_id="agent-hub",
            bash_available=True,
            agent_slug="persona",
        )
    cmd = mocked.call_args.args[0]
    assert cmd[:4] == ["st", "tools", "manifest", "--format"]
    assert cmd[4] == "inject"
    assert "--task" in cmd and cmd[cmd.index("--task") + 1] == "devops"
    assert "--agent" in cmd and cmd[cmd.index("--agent") + 1] == "persona"
    assert "--profile" in cmd and cmd[cmd.index("--profile") + 1] == "agent_runtime"


def test_format_tool_capability_context_drops_filter_for_chat_runtime() -> None:
    _clear_cache()
    with patch.object(tcc, "run_process", return_value=_stub_run(stdout="mandates: {}")) as mocked:
        tcc.format_tool_capability_context(
            consumer_profile="agent_preview",
            task_type="chat",
            project_id="agent-hub",
            bash_available=True,
        )
    cmd = mocked.call_args.args[0]
    assert "--task" not in cmd


def test_format_tool_capability_context_returns_empty_when_bash_unavailable() -> None:
    _clear_cache()
    with patch.object(tcc, "run_process") as mocked:
        rendered = tcc.format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="wake",
            project_id="monkey-fight",
            bash_available=False,
        )
    assert rendered == ""
    mocked.assert_not_called()


def test_format_tool_capability_context_fails_closed_for_persona_without_bash() -> None:
    _clear_cache()
    rendered = tcc.format_tool_capability_context(
        consumer_profile="agent_runtime",
        task_type="wake",
        project_id="agent-hub",
        bash_available=None,
        agent_slug="persona",
    )
    assert rendered == ""


def test_format_tool_capability_context_returns_empty_when_manifest_empty() -> None:
    _clear_cache()
    with patch.object(tcc, "run_process", return_value=_stub_run(stdout="")):
        rendered = tcc.format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id="agent-hub",
            bash_available=True,
        )
    assert rendered == ""


def test_format_tool_capability_context_sanitizes_python_env() -> None:
    _clear_cache()
    captured: dict = {}

    def _capture(cmd, **kwargs):
        captured.update(kwargs)
        return _stub_run(stdout="mandates: {}")

    with patch.dict(
        tcc.os.environ, {"PYTHONPATH": "/tmp/bad", "PYTHONHOME": "/tmp/also-bad"}, clear=False
    ), patch.object(tcc, "run_process", side_effect=_capture):
        tcc.format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id="agent-hub",
            bash_available=True,
        )

    env = captured["env"]
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_build_tool_capability_payload_wraps_inject_body() -> None:
    _clear_cache()
    with patch.object(tcc, "run_process", return_value=_stub_run(stdout="mandates: {}")):
        payload = tcc.build_tool_capability_payload(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id="agent-hub",
            bash_available=True,
        )
    assert payload is not None
    assert payload["tool_usage"].startswith("<tool-usage>")
