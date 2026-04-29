from __future__ import annotations

from app.services.memory.st_usage_memory import (
    build_st_usage_memory_from_commands,
    parse_st_command,
)


def test_parse_st_command_handles_project_flag_and_subcommands() -> None:
    memory_get = parse_st_command("st -P agent-hub memory get 115b32e3")
    agent_preview = parse_st_command("$ st agents preview coder --json")

    assert memory_get is not None
    assert memory_get.key == "memory get"
    assert agent_preview is not None
    assert agent_preview.key == "agents preview"
    assert parse_st_command("python -m something") is None


def test_parse_st_command_tracks_help_without_using_help_as_key() -> None:
    parsed = parse_st_command("st memory search --help")

    assert parsed is not None
    assert parsed.key == "memory search"
    assert parsed.is_help is True


def test_build_st_usage_memory_combines_curated_base_and_tracked_subcommands() -> None:
    memory = build_st_usage_memory_from_commands(
        [
            "st agents preview coder --json",
            "st agents preview persona --json",
            "st db query -t 'SELECT 1'",
            "st browser check http://localhost:3003 /tmp/page.png",
            "st memory search --help",
        ],
        task_type="frontend",
        max_entries=8,
    )

    assert memory.observed == 5
    assert memory.quick[0].startswith("st pulse --gate")
    assert any("no raw git/jj" in entry for entry in memory.quick)
    assert any(entry.startswith("st agents preview") for entry in memory.quick)
    assert any(entry.startswith("st browser check") for entry in memory.quick)
    assert all("--help" not in entry for entry in memory.quick)
