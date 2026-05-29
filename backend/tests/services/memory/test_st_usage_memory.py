from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.memory.st_usage_memory import (
    _SCORE_HALF_LIFE_DAYS,
    _decay_scores_from_rows,
    build_st_usage_memory_from_commands,
    parse_st_command,
)


def test_decay_scores_recency_weighting_and_help_exclusion() -> None:
    now = datetime(2026, 5, 29, tzinfo=UTC)
    rows = [
        ("st pulse --gate", None, now),  # age 0 -> weight 1.0
        ("st db query -t x", None, now - timedelta(days=_SCORE_HALF_LIFE_DAYS)),  # 1 half-life -> 0.5
        ("st memory search foo --help", None, now),  # help -> excluded from scoring
    ]

    weights, parsed = _decay_scores_from_rows(rows, now=now)

    assert parsed == 2  # the --help row is excluded
    assert abs(weights["pulse"] - 1.0) < 1e-6
    assert abs(weights["db query"] - 0.5) < 1e-6
    assert "memory search" not in weights


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


def test_build_st_usage_memory_is_telemetry_only_no_curated_seed() -> None:
    """Quick-use seeding moved to `st tools manifest`; this surface emits telemetry only."""
    memory = build_st_usage_memory_from_commands(
        [
            "st agents preview coder --json",
            "st agents preview persona --json",
            "st db query -t 'SELECT 1'",
            "st browser check http://localhost:3003 /tmp/page.png",
            "st memory search --help",
        ],
        task_type="frontend",
        max_entries=10,
    )

    assert memory.observed == 5
    assert memory.help_count == 1
    assert memory.quick == []
    assert memory.quick_entries == []
    metric_keys = {metric.command_key for metric in memory.command_metrics}
    assert metric_keys == {"agents preview", "db query", "browser check", "memory search"}
    for metric in memory.command_metrics:
        assert metric.injected_example is None


def test_parse_st_command_tracks_graph_subcommands_for_quick_use_memory() -> None:
    graph_query = parse_st_command('st graph query "auth topology" --project summitflow')
    graph_fallow = parse_st_command("st graph fallow audit --project summitflow")

    assert graph_query is not None
    assert graph_query.key == "graph query"
    assert graph_fallow is not None
    assert graph_fallow.key == "graph fallow"
