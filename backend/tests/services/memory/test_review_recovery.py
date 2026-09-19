"""Bounded persistence and retry identity for scheduled memory reviews."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory_unified import MemoryReviewRun
from app.services.memory._review_agent_runner import (
    _find_matching_attempt,
    _record_context_review,
    _review_attempt_key,
)


def _sources(revision: str = "sha256:one") -> list[dict[str, str]]:
    return [
        {
            "source_type": "memory",
            "source_id": "11111111-1111-1111-1111-111111111111",
            "revision": revision,
            "content": "Keep this exact source snapshot.",
        }
    ]


def test_review_attempt_key_changes_when_source_or_reviewer_changes() -> None:
    kwargs = {
        "evidence": {"sources": _sources(), "prompt_builder": "v1"},
    }
    original = _review_attempt_key(reviewer_identity="identity-a", **kwargs)
    changed_source = _review_attempt_key(
        reviewer_identity="identity-a",
        evidence={"sources": _sources("sha256:two"), "prompt_builder": "v1"},
    )
    changed_reviewer = _review_attempt_key(reviewer_identity="identity-b", **kwargs)

    assert original != changed_source
    assert original != changed_reviewer
    # Selection controls such as force_all are intentionally outside the
    # identity: explicitly forcing the same failed evidence cannot buy a
    # second identical provider attempt.
    assert _review_attempt_key(reviewer_identity="identity-a", **kwargs) == original


def test_unrelated_library_growth_does_not_retry_the_same_failed_evidence() -> None:
    evidence = {"sources": _sources(), "coverage": {"exhaustive": False, "omitted_sources": 10}}
    original = _review_attempt_key(reviewer_identity="identity-a", evidence=evidence)
    evidence["coverage"]["omitted_sources"] = 11
    assert _review_attempt_key(reviewer_identity="identity-a", evidence=evidence) == original


@pytest.mark.asyncio
async def test_failure_receipt_preserves_exact_sources_and_run_evidence() -> None:
    run = MemoryReviewRun(
        reviewer_agent_slug="memory-curator",
        batch_limit=1,
        metadata_={"attempt": {"key": "attempt-key"}},
    )
    db = AsyncMock()
    recorded = AsyncMock(return_value="review-id")
    raw_content = "partial response " * 1000

    with patch(
        "app.services.context_governance.record",
        new=recorded,
    ):
        receipt = await _record_context_review(
            db,
            run=run,
            sources=_sources(),
            reviewer_agent_slug="memory-curator",
            reviewer_model_id="codex/gpt-5.5",
            reviewer_identity="identity-a",
            session_id="session-1",
            failure="provider unavailable",
            failure_type="ProviderError",
            raw_content=raw_content,
        )

    assert receipt == "review-id"
    payload = recorded.call_args.args[3]
    assert payload["review_workflow"] == "memory_batch"
    assert payload["sources"] == _sources()
    assert payload["reviewer_identity"] == "identity-a"
    assert payload["reviewer"]["session_id"] == "session-1"
    assert payload["failure_evidence"]["reviewer_model_id"] == "codex/gpt-5.5"
    assert payload["failure_evidence"]["raw_content"] == raw_content


@pytest.mark.asyncio
async def test_completed_attempt_does_not_block_a_later_explicit_review() -> None:
    completed = MemoryReviewRun(
        reviewer_agent_slug="memory-curator",
        batch_limit=1,
        status="completed",
        metadata_={"attempt": {"key": "same-key", "status": "completed"}},
    )
    failed = MemoryReviewRun(
        reviewer_agent_slug="memory-curator",
        batch_limit=1,
        status="failed",
        metadata_={"attempt": {"key": "same-key", "status": "failed"}},
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [completed, failed]
    db = AsyncMock()
    db.execute.return_value = result

    assert await _find_matching_attempt(db, "same-key") is None

    result.scalars.return_value.all.return_value = [failed, completed]
    assert await _find_matching_attempt(db, "same-key") is failed

    result.scalars.return_value.all.return_value = [completed]
    assert await _find_matching_attempt(db, "same-key") is None
