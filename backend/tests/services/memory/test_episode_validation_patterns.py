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
