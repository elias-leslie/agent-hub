"""Regression tests for episode validation pattern performance and coverage."""

from __future__ import annotations

import time

from app.services.memory.episode_validation import EpisodeValidator


def test_task_execution_log_pattern_still_detects_subtask_attempts() -> None:
    assert EpisodeValidator._detect_non_reusable_patterns("Subtask 1-2 failed after 3 attempts") == [
        "task execution log"
    ]


def test_task_execution_log_pattern_is_linear_on_long_hyphen_runs() -> None:
    content = "subtask " + "-" * 50_000
    started = time.monotonic()
    assert EpisodeValidator._detect_non_reusable_patterns(content) == []
    assert time.monotonic() - started < 1.0


def test_task_execution_log_pattern_is_linear_on_repeated_subtask_tokens() -> None:
    for content in ("subtask a " * 50_000, "subtask a\n" * 50_000, "subtask" * 50_000 + " x"):
        started = time.monotonic()
        assert EpisodeValidator._detect_non_reusable_patterns(content) == []
        assert time.monotonic() - started < 1.0


def test_subtask_attempt_detection_matches_original_line_semantics() -> None:
    detect = EpisodeValidator._has_subtask_attempt_log
    # "attempts" must follow the subtask id on the same line ...
    assert detect("subtask 3 failed after 2 attempts")
    assert detect("noise subtask a then subtask b retried, attempt 2")
    assert not detect("subtask 3 failed\nafter 2 attempts")
    assert not detect("attempts before subtask 3")
    assert not detect("subtask 3 attemptsx")
    # ... but the whitespace after "subtask" may cross a newline,
    assert detect("subtask\n7 attempts")
    # and the id character can start the next "subtask" token.
    assert detect("subtask\nSubTask\nabc attempt.")
