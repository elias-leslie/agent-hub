from __future__ import annotations

from app.workflows._session_postprocess import (
    inline_summary_contract_issues,
    progress_tag_contract_issues,
)


def test_inline_summary_contract_requires_final_line_outcome_summary() -> None:
    issues = inline_summary_contract_issues(
        "Did the work. [[S:completed:Finished the scoped repair.]]"
    )

    assert issues == []


def test_inline_summary_contract_flags_nonfinal_summary() -> None:
    issues = inline_summary_contract_issues(
        "[[S:completed:Finished the scoped repair.]] Next I will publish the branch."
    )

    assert "inline summary tag is not the final line" in issues


def test_progress_tag_contract_requires_start_and_later_proof() -> None:
    issues = progress_tag_contract_issues(
        (
            "[[P:started:reading the assigned task context]] "
            "[[P:tested:dt -q -d passes clean after the fix]] "
            "[[S:completed:Validated and finished the requested change.]]"
        ),
        require_progress=True,
    )

    assert issues == []


def test_progress_tag_contract_flags_mirrored_free_text() -> None:
    issues = progress_tag_contract_issues(
        (
            "[[P:started:working on task-12345678]] Working on task-12345678. "
            "[[P:tested:dt -q -d passes clean]]"
        ),
        require_progress=True,
    )

    assert "progress tag content is duplicated in surrounding prose" in issues
