from __future__ import annotations

from unittest.mock import patch


def test_format_tool_capability_context_renders_compact_yaml_for_runtime() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n  memory  Memory ops\n  prompt  Prompt ops\n  complete  Complete\n",
        ("dt", "--help"): "Dev Standards\n\nSubcommands (TOON output for Claude):\n  pytest  Run pytest\n  ruff  Run ruff\nOptions:\n  --check, -c  Full check\n  --quick, -q  Quick check\n",
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
        )

    assert "<tool-capabilities>" in rendered
    assert "tool: st" in rendered
    assert "discover: st --help" in rendered
    assert "commands:" in rendered
    assert "--check" in rendered
    assert "rebuild.sh" in rendered


def test_format_tool_capability_context_skips_project_only_and_frontend_tools_when_not_applicable() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n  memory  Memory ops\n",
        ("dt", "--help"): "Dev Standards\n\nSubcommands (TOON output for Claude):\n  pytest  Run pytest\nOptions:\n  --check, -c  Full check\n",
        ("db", "--help"): "Database CLI\n\nCommands:\n  tables                    List tables\n",
        ("web-research", "--help"): "usage: web-research [-h] {search,research,fetch} ...\n\nRun centralized web research using Agent Hub's shared tool stack.\n\npositional arguments:\n  {search,research,fetch}\n    search              Search the public web.\n",
        ("rebuild.sh", "--help"): "Usage: rebuild.sh [--detach] [--include-all-workers] <project>\n",
        ("sf-browser", "--help"): "agent-browser\n\nCore Commands:\n  open <url>    Navigate\n  snapshot      Snapshot\nSessions:\n  session       Session info\n",
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
    assert "sf-browser" not in rendered


def test_format_tool_capability_context_keeps_core_tools_for_chat_runtime() -> None:
    from app.services.memory.tool_capability_context import format_tool_capability_context

    help_outputs = {
        ("st", "--help"): "Usage: st [OPTIONS] COMMAND [ARGS]...\n\nCommands:\n  search  Search code\n  memory  Memory ops\n",
        ("dt", "--help"): "Dev Standards\n\nSubcommands (TOON output for Claude):\n  pytest  Run pytest\nOptions:\n  --check, -c  Full check\n",
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
    assert "tool: dt" in rendered
    assert "tool: rebuild.sh" in rendered
