"""Tests for bounded completion-review prompt guidance."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.persona_prompt_service import render_completion_review_rules
from app.workflows._completion_review import _build_review_prompt
from scripts.completion_review_benchmark_cases import get_completion_review_case_by_id


@pytest.fixture(autouse=True)
def _mock_completion_review_prompts():
    async def _require_prompt_content(slug: str) -> str:
        if slug == "completion-review-rules":
            return (
                "- Any `completed_ready_for_closure` item means closure residue still remains; choose `continue` with focus on closeout.\n"
                "- Any `active_running_task` with `recent_progress=yes` means the lane is still healthy; choose `continue` and focus on monitoring or follow-through, not redispatch.\n"
                "- A healthy `waiting_external` lane with no actionable cleanup is compatible with `complete`.\n"
                "- If cleanup/workstream point to one clear unfinished residue chain, choose `continue`.\n"
                "- If cleanup residue and workstream state disagree about the type of remaining work, treat that as conflicting evidence.\n"
                "- Choose `escalate` only when cleanup/workstream evidence is itself contradictory or too ambiguous to map to one concrete follow-up.\n"
            )
        if slug == "completion-review-prompt":
            return (
                "You are performing a bounded completion review for a finished persona session.\n\n"
                "{review_rules}\n\n"
                "<heartbeat_output>\n{completion_content}\n</heartbeat_output>\n\n"
                "<cleanup_status>\n{cleanup_status}\n</cleanup_status>\n\n"
                "<workstream_inventory>\n{workstream_inventory}\n</workstream_inventory>\n\n"
                "Return JSON only with fields `decision`, `reason`, and `focus`."
            )
        raise AssertionError(f"unexpected prompt slug: {slug}")

    with patch("app.services.persona_prompt_service.require_prompt_content", new=_require_prompt_content):
        yield


@pytest.mark.asyncio
async def test_build_review_prompt_includes_closeout_and_ambiguity_rules() -> None:
    prompt = await _build_review_prompt(
        completion_content="HEARTBEAT_OK — All residue resolved.",
        cleanup_status="ACTIONABLE-CLEANUP[1]\n- agent-hub | salvage | task-999",
        workstream_inventory='- task-999 | state=completed_ready_for_closure | next=bash: st context task-999 then st done task-999 --admin --message "Completed work verified; task closed."',
    )

    assert "Any `completed_ready_for_closure` item" in prompt
    assert "Any `active_running_task` with `recent_progress=yes`" in prompt
    assert "If cleanup/workstream point to one clear unfinished residue chain, choose `continue`" in prompt
    assert "If cleanup residue and workstream state disagree about the type of remaining work" in prompt
    assert "Choose `escalate` only when cleanup/workstream evidence is itself contradictory" in prompt
    assert "A healthy `waiting_external` lane" in prompt


@pytest.mark.asyncio
async def test_completion_review_benchmark_prompt_uses_shared_rules() -> None:
    case = get_completion_review_case_by_id("review_ambiguous_conflict")

    prompt = await case.build_prompt()

    assert await render_completion_review_rules(header="Decision rules") in prompt
