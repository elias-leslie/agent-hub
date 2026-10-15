"""Regression tests for episode validation pattern performance and coverage."""

from __future__ import annotations

import time

import pytest

from app.services.memory.episode_validation import EpisodeValidationError, EpisodeValidator


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


_PYTEST_DUMP = """**DT CLI**: run dt check before commit.
$ dt check --quick
TEST:FAIL:1|details:.dev-tools/pytest.txt
FAILED tests/test_x.py::test_y - AssertionError
E       assert 1 == 2
===== 1 failed, 20 passed in 1.2s =====
"""


def test_tool_output_dump_is_rejected_on_update() -> None:
    with pytest.raises(EpisodeValidationError, match="tool output"):
        EpisodeValidator.validate_update(_PYTEST_DUMP, previous="**DT CLI**: run dt check.", tier="reference")


def test_traceback_counts_as_tool_output() -> None:
    content = 'Rule.\nTraceback (most recent call last):\n  File "a.py", line 3, in f\n  File "b.py", line 9, in g\n'
    assert EpisodeValidator.looks_like_tool_output(content)
    assert "tool output transcript" in EpisodeValidator._detect_non_reusable_patterns(content)


def test_a_single_command_example_is_not_tool_output() -> None:
    content = "**Deploy**: rebuild with the managed path.\n$ st service rebuild agent-hub --detach\n"
    assert not EpisodeValidator.looks_like_tool_output(content)
    EpisodeValidator.validate_update(content, previous="old", tier="mandate")


def test_compact_tier_cannot_balloon_on_update() -> None:
    previous = "x" * 352
    with pytest.raises(EpisodeValidationError, match="352 to 3234"):
        EpisodeValidator.validate_update("y" * 3234, previous=previous, tier="guardrail")
    # Reference tier and modest growth stay allowed.
    EpisodeValidator.validate_update("y" * 3234, previous=previous, tier="reference")
    EpisodeValidator.validate_update("y" * 900, previous=previous, tier="mandate")


def test_tool_output_detection_is_linear_on_long_lines() -> None:
    content = ("=" * 200_000 + " passed\n") + ("E" + " " * 200_000 + "\n")
    start = time.perf_counter()
    EpisodeValidator.looks_like_tool_output(content)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    ("added", "pattern"),
    [
        ("## Heartbeat: 03:00 all quiet", "heartbeat journal"),
        ("Merge of task task-abc123 landed", "task execution log"),
        ("subtask 2.1 took 3 attempts", "task execution log"),
        ("[Session summary: fixed the thing]", "session summary"),
    ],
)
def test_update_cannot_add_operational_log_lines(added: str, pattern: str) -> None:
    previous = "**Deploy**: rebuild with the managed path."
    with pytest.raises(EpisodeValidationError) as raised:
        EpisodeValidator.validate_update(f"{previous}\n{added}", previous=previous, tier="reference")
    assert pattern in raised.value.detected_patterns


def test_update_may_keep_a_match_it_already_had() -> None:
    # Older memories that already match a detector stay editable; only added lines count.
    previous = "**Rule**: see task-abc123 for the incident.\nKeep it short."
    EpisodeValidator.validate_update(
        "**Rule**: see task-abc123 for the incident.\nKeep it shorter.", previous=previous, tier="reference"
    )
