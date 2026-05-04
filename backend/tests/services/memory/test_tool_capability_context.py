from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_format_tool_capability_context_renders_compact_yaml_for_runtime() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  list  List tasks\n  ready  Ready tasks\n  context  Task context\n  feedback  Feedback ops\n  search  Search code\n  memory  Memory ops\n  graph  Graphify ops\n  prompt  Prompt ops\n  complete  Complete\n  check  Quality checks\n",
        ("db", "--help"): "Database CLI\n\nCommands:\n  tables                    List tables\n  query \"SELECT ...\"        Execute query\nMigration Commands:\n  migrate status            Show current revision\n",
        ("web-research", "--help"): "usage: web-research [-h] {search,research,fetch} ...\n\nRun centralized web research using Agent Hub's shared tool stack.\n\npositional arguments:\n  {search,research,fetch}\n    search              Search the public web.\n    research            Search first, then fetch one result.\n    fetch               Fetch and extract a webpage.\n",
        ("rebuild.sh", "--help"): "Usage: rebuild.sh [--detach] [--include-all-workers] <project>\n",
    }

    with patch(
        "app.services.memory.tool_capability_context._read_help_output",
        side_effect=lambda command: help_outputs.get(command, ""),
    ):
        rendered = format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id="agent-hub",
            st_quick=["st pulse --gate | preflight; edit only if clear"],
        )

    assert "<tool-capabilities>" in rendered
    assert "tool: st" in rendered
    assert "discover: st --help" in rendered
    assert "commands:" in rendered
    assert "list" in rendered
    assert "ready" in rendered
    assert "context" in rendered
    assert "feedback" in rendered
    assert "graph" in rendered
    assert "quick:" in rendered
    assert "st pulse --gate" in rendered
    assert "check" in rendered
    assert "rebuild.sh" in rendered


def test_format_tool_capability_context_skips_project_only_and_frontend_tools_when_not_applicable() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n  memory  Memory ops\n",
        ("db", "--help"): "Database CLI\n\nCommands:\n  tables                    List tables\n",
        ("web-research", "--help"): "usage: web-research [-h] {search,research,fetch} ...\n\nRun centralized web research using Agent Hub's shared tool stack.\n\npositional arguments:\n  {search,research,fetch}\n    search              Search the public web.\n",
        ("rebuild.sh", "--help"): "Usage: rebuild.sh [--detach] [--include-all-workers] <project>\n",
        ("st browser", "--help"): "Remote browser automation\n\nCommands:\n  open <url>    Navigate\n  snapshot      Snapshot\n",
    }

    with patch(
        "app.services.memory.tool_capability_context._read_help_output",
        side_effect=lambda command: help_outputs.get(command, ""),
    ):
        rendered = format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="backend",
            project_id=None,
        )

    assert "rebuild.sh" not in rendered
    assert "st browser" not in rendered


def test_format_tool_capability_context_keeps_core_tools_for_chat_runtime() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n  memory  Memory ops\n",
        ("db", "--help"): "Database CLI\n\nCommands:\n  tables                    List tables\n",
        ("web-research", "--help"): "usage: web-research [-h] {search,research,fetch} ...\n\nRun centralized web research using Agent Hub's shared tool stack.\n\npositional arguments:\n  {search,research,fetch}\n    search              Search the public web.\n",
        ("rebuild.sh", "--help"): "Usage: rebuild.sh [--detach] [--include-all-workers] <project>\n",
    }

    with patch(
        "app.services.memory.tool_capability_context._read_help_output",
        side_effect=lambda command: help_outputs.get(command, ""),
    ):
        rendered = format_tool_capability_context(
            consumer_profile="agent_preview",
            task_type="chat",
            project_id="agent-hub",
        )

    assert "tool: st" in rendered
    assert "tool: rebuild.sh" in rendered


def test_format_tool_capability_context_omits_cli_wrappers_without_bash() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n",
        ("db", "--help"): "Database CLI\n\nCommands:\n  tables                    List tables\n",
        ("web-research", "--help"): "usage: web-research [-h] {search,research,fetch} ...\n",
        ("rebuild.sh", "--help"): "Usage: rebuild.sh [--detach] <project>\n",
    }

    with patch(
        "app.services.memory.tool_capability_context._read_help_output",
        side_effect=lambda command: help_outputs.get(command, ""),
    ):
        rendered = format_tool_capability_context(
            consumer_profile="agent_runtime",
            task_type="wake",
            project_id="monkey-fight",
            bash_available=False,
        )

    assert rendered == ""


def test_read_help_output_sanitizes_python_env_for_external_clis() -> None:
    from app.services.memory.tool_capability_context import _read_help_output

    _read_help_output.cache_clear()

    with patch.dict(
        "app.services.memory.tool_capability_context.os.environ",
        {"PYTHONPATH": "/tmp/bad", "PYTHONHOME": "/tmp/also-bad"},
        clear=True,
    ), patch(
        "app.services.memory.tool_capability_context.run_process",
        return_value=SimpleNamespace(
            stdout="Usage: st [OPTIONS] COMMAND [ARGS]...\n",
            stderr="",
            returncode=0,
        ),
    ) as mocked_run:
        rendered = _read_help_output(("st", "--help"))

    assert rendered.startswith("Usage: st")
    env = mocked_run.call_args.kwargs["env"]
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_read_help_output_ignores_stderr_tracebacks() -> None:
    from app.services.memory.tool_capability_context import _read_help_output

    _read_help_output.cache_clear()

    with patch(
        "app.services.memory.tool_capability_context.run_process",
        return_value=SimpleNamespace(
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "  File \"/home/kasadis/bin/st\", line 4, in <module>\n"
                "ModuleNotFoundError: No module named 'app.storage.connection'\n"
            ),
            returncode=1,
        ),
    ):
        rendered = _read_help_output(("st", "--help"))

    assert rendered == ""


def test_description_from_help_falls_back_for_generic_headings() -> None:
    from app.services.memory.tool_capability_context import _description_from_help

    description = _description_from_help(
        "Usage: rebuild.sh [--detach] [--include-all-workers] <project>\n\nAvailable projects:\n",
        "Project rebuild helper",
    )

    assert description == "Project rebuild helper"
