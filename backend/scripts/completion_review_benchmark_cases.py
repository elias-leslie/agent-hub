"""Benchmark cases for the bounded supervisor completion-review role."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.constants import CLAUDE_OPUS, CODEX_GPT_5_5
from app.services.persona_prompt_service import render_completion_review_rules

DEFAULT_COMPLETION_REVIEW_MODELS = [
    CODEX_GPT_5_5,
    CLAUDE_OPUS,
]

_RESPONSE_SHAPE = """Return JSON only with this exact shape:
{
  "case_id": "<copy the case id>",
  "decision": "complete|continue|escalate",
  "confidence": "low|medium|high",
  "reason": "one or two sentences",
  "focus": "one short phrase"
}"""


@dataclass(frozen=True)
class CompletionReviewBenchmarkCase:
    case_id: str
    name: str
    description: str
    heartbeat_output: str
    cleanup_status: str
    workstream_inventory: str
    expected_decision: str
    expected_focus_terms: tuple[str, ...] = field(default_factory=tuple)
    reviewer_invoked: bool = True

    async def build_prompt(self) -> str:
        return (
            f"Benchmark case id: {self.case_id}\n"
            "You are the bounded supervisor completion reviewer for the persona.\n"
            "Judge only whether the finished session should be accepted as complete, "
            "continued with one focused follow-up, or escalated for ambiguity.\n\n"
            f"{await render_completion_review_rules(header='Decision rules')}\n\n"
            f"{_RESPONSE_SHAPE}\n\n"
            "<heartbeat_output>\n"
            f"{self.heartbeat_output}\n"
            "</heartbeat_output>\n\n"
            "<cleanup_status>\n"
            f"{self.cleanup_status}\n"
            "</cleanup_status>\n\n"
            "<workstream_inventory>\n"
            f"{self.workstream_inventory}\n"
            "</workstream_inventory>\n"
        )


def get_completion_review_benchmark_cases() -> list[CompletionReviewBenchmarkCase]:
    return [
        CompletionReviewBenchmarkCase(
            case_id="review_cleanup_false_complete",
            name="Cleanup False Complete",
            description="Reviewer should reject a HEARTBEAT_OK that still leaves actionable cleanup residue.",
            heartbeat_output="HEARTBEAT_OK — Routine sweep complete.",
            cleanup_status="ACTIONABLE-CLEANUP[1]\n- agent-hub | finalize | task-123",
            workstream_inventory="",
            expected_decision="continue",
            expected_focus_terms=("cleanup", "finalize"),
            reviewer_invoked=False,
        ),
        CompletionReviewBenchmarkCase(
            case_id="review_recent_progress_patience",
            name="Recent Progress Patience",
            description="Reviewer should tell the persona to continue when a quiet active session still has recent progress.",
            heartbeat_output="HEARTBEAT_OK — No follow-up required.",
            cleanup_status="CLEANUP[current]:repos=1 needs_cleanup=0 checkpoints=0 dirty=0 orphan=0 prunable=0",
            workstream_inventory=(
                "- task-abc | state=active_running_task | recent_progress=yes | "
                "health=active | quiet_for_seconds=180 | next=inspect_existing_lane"
            ),
            expected_decision="continue",
            expected_focus_terms=("progress", "inspect|monitor"),
        ),
        CompletionReviewBenchmarkCase(
            case_id="review_quiet_healthy_true_complete",
            name="Quiet Healthy True Complete",
            description="Reviewer should not force a follow-up when the remaining session state is quiet but healthy.",
            heartbeat_output="HEARTBEAT_OK — Monitoring confirms the remaining lane is healthy and needs no further action.",
            cleanup_status="CLEANUP[current]:repos=1 needs_cleanup=0 checkpoints=0 dirty=0 orphan=0 prunable=0",
            workstream_inventory=(
                "- task-quiet | state=waiting_external | recent_progress=no | "
                "health=healthy | quiet_for_seconds=960 | next=await_external_signal"
            ),
            expected_decision="complete",
            expected_focus_terms=("healthy",),
        ),
        CompletionReviewBenchmarkCase(
            case_id="review_true_complete_clean",
            name="True Complete Clean",
            description="Reviewer should accept a HEARTBEAT_OK when no residue remains.",
            heartbeat_output="HEARTBEAT_OK — Finished cleanup and left all projects in known-good state.",
            cleanup_status="CLEANUP[current]:repos=1 needs_cleanup=0 checkpoints=0 dirty=0 orphan=0 prunable=0",
            workstream_inventory="",
            expected_decision="complete",
            expected_focus_terms=("clean",),
        ),
        CompletionReviewBenchmarkCase(
            case_id="review_completed_ready_for_closure",
            name="Completed Ready For Closure",
            description="Reviewer should continue when closeout residue remains.",
            heartbeat_output="HEARTBEAT_OK — Everything has been wrapped up.",
            cleanup_status="CLEANUP[current]:repos=1 needs_cleanup=0 checkpoints=0 dirty=0 orphan=0 prunable=0",
            workstream_inventory='- task-def | state=completed_ready_for_closure | next=manage_tasks(action="done")',
            expected_decision="continue",
            expected_focus_terms=("closure", "done"),
            reviewer_invoked=False,
        ),
        CompletionReviewBenchmarkCase(
            case_id="review_ambiguous_conflict",
            name="Ambiguous Conflict",
            description=(
                "Reviewer should escalate when all three signals disagree: heartbeat claims clean, "
                "cleanup says salvage needed, workstream says task is active with progress. "
                "No single concrete follow-up can be derived."
            ),
            heartbeat_output="HEARTBEAT_OK — All residue resolved.",
            cleanup_status="ACTIONABLE-CLEANUP[1]\n- agent-hub | salvage | task-999",
            workstream_inventory=(
                "- task-999 | state=active_running_task | recent_progress=yes | "
                "health=active | quiet_for_seconds=60 | next=inspect_existing_lane"
            ),
            expected_decision="escalate",
            expected_focus_terms=("contradict|conflict|ambig",),
            reviewer_invoked=False,
        ),
    ]


def get_default_completion_review_case_ids() -> list[str]:
    return [
        case.case_id
        for case in get_completion_review_benchmark_cases()
        if case.reviewer_invoked
    ]


def get_completion_review_case_by_id(case_id: str) -> CompletionReviewBenchmarkCase:
    for case in get_completion_review_benchmark_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown completion-review benchmark case: {case_id}")
