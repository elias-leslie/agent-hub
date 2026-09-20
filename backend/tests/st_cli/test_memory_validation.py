"""Tests for memory format validation rules."""

from __future__ import annotations

import pytest
import typer
from agent_hub_st.memory_validation import build_episode_content, validate_content_format


def test_validate_content_format_accepts_topic_header() -> None:
    validate_content_format(
        "**Quality Checks**: Use dt for all quality checks. Never run raw pytest or ruff.",
        "Use dt for checks",
        "mandate",
    )


def test_validate_content_format_accepts_missing_bold_topic_header() -> None:
    validate_content_format(
        "Use dt for all quality checks.",
        "Use dt for checks",
        "mandate",
    )


def test_validate_content_format_accepts_reserved_tier_header() -> None:
    validate_content_format(
        "**Mandate**: Use dt for all quality checks.",
        "Use dt for checks",
        "mandate",
    )


def test_validate_content_format_accepts_weak_imperative() -> None:
    validate_content_format(
        "**Git Safety**: Git commits should use /commit_it when available.",
        "Use commit flow",
        "mandate",
    )


def test_validate_content_format_accepts_conversational_language() -> None:
    validate_content_format(
        "**Deletion Safety**: Please remember to grep before deleting code.",
        "Grep before deletion",
        "guardrail",
    )


def test_validate_content_format_error_includes_quickstart(capsys) -> None:
    with pytest.raises(typer.Exit):
        validate_content_format(
            "Use dt for all quality checks.",
            "Use dt for checks",
            "unsupported",
        )

    err = capsys.readouterr().err
    assert 'st memory save -s project --scope-id a-term -t reference' in err
    assert 'st memory format --topic "Network evidence"' in err


def test_validate_content_format_allows_long_single_rule_without_hint(capsys) -> None:
    validate_content_format(
        (
            "**Memory Headers**: Use compact bold topic headers for memory episodes so retrieval stays clean and bodies stay terse. "
            "Prefer keeping each rule compact even when a slightly longer explanation is clearer than splitting one rule into multiple entries across fragmented memories and retrieval paths that dilute authority cues."
        ),
        "Use compact memory headers",
        "reference",
    )

    err = capsys.readouterr().err
    assert err == ""


def test_build_episode_content_normalizes_topic_whitespace() -> None:
    content = build_episode_content(
        "  Memory   Headers  ",
        "Use compact topic headers",
    )

    assert content == "**Memory Headers**: Use compact topic headers."


def test_build_episode_content_rejects_topic_markup() -> None:
    with pytest.raises(typer.BadParameter):
        build_episode_content("**Bad Topic**", "Use compact topic headers")
