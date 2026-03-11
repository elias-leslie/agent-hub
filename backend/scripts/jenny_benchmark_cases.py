"""Benchmark roster and scenario definitions for Jenny model profiling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_JENNY_BENCHMARK_MODELS = [
    "codex/gpt-5.4",
    "codex/gpt-5.3-codex",
    "codex/gpt-5.3-codex-spark",
    "codex/gpt-5.2",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

_RESPONSE_SHAPE = """Return JSON only with this exact shape:
{
  "case_id": "<copy the case id>",
  "primary_action": "dispatch|monitor|block|wait|reconcile",
  "should_dispatch": true,
  "should_close": false,
  "confidence": "low|medium|high",
  "summary": "one sentence"
}"""


@dataclass(frozen=True)
class JennyBenchmarkCase:
    """One reproducible Jenny benchmark scenario."""

    case_id: str
    name: str
    description: str
    scenario: str
    expected: dict[str, object]
    require_tool_call: bool = False
    required_tool_names: tuple[str, ...] = ()
    max_turns: int = 1
    execute_tools: bool = False
    fixture_files: dict[str, str] = field(default_factory=dict)
    required_summary_terms: tuple[str, ...] = ()
    required_project_id: str | None = None

    def build_prompt(self) -> str:
        """Build the user prompt shown to Jenny for this benchmark case."""
        tool_instruction = ""
        if self.required_tool_names:
            required_tools = ", ".join(self.required_tool_names)
            tool_instruction = (
                f"\nYou must use these tools before answering: {required_tools}. "
                "A correct answer that skips them will fail this benchmark."
            )
            if "precision_code_search" in self.required_tool_names:
                tool_instruction += (
                    " Use precision_code_search as your first code-navigation step. "
                    "Do not rely on read_file, bash, or assumptions as the primary lookup path."
                )
        elif self.require_tool_call:
            tool_instruction = (
                "\nYou must inspect the files in the working directory before answering. "
                "Only inspect task.txt, cleanup.txt, and sessions.txt in the current working directory. "
                "Do not search outside the current working directory or answer from assumptions."
            )
        return (
            f"Benchmark case id: {self.case_id}\n"
            "You are Jenny in a controlled evaluation. "
            "Make the governance decision you would actually take.\n"
            f"{tool_instruction}\n\n"
            f"{_RESPONSE_SHAPE}\n\n"
            "Scenario:\n"
            f"{self.scenario}\n"
        )


def get_jenny_benchmark_cases() -> list[JennyBenchmarkCase]:
    """Return the fixed benchmark battery used for Jenny model comparisons."""
    return [
        JennyBenchmarkCase(
            case_id="ready_task_dispatch",
            name="Ready Task Dispatch",
            description="Dispatch a fully scoped ready task with no overlap or cleanup blockers.",
            scenario=(
                "TASK: task-1111\n"
                "status=pending\n"
                "priority=P2\n"
                "type=task\n"
                "ready=yes\n"
                "objective=Refactor session summary serializer to remove duplicate formatting logic.\n"
                "done_when=Serializer has one source of truth, tests updated, dt -q -d passes.\n"
                "active_same_task_lane=no\n"
                "cleanup_status=clean\n"
                "recommended_next_step=dispatch execution specialist.\n"
            ),
            expected={
                "case_id": "ready_task_dispatch",
                "primary_action": "dispatch",
                "should_dispatch": True,
                "should_close": False,
            },
        ),
        JennyBenchmarkCase(
            case_id="same_task_overlap",
            name="Same Task Overlap",
            description="Do not redispatch when an active same-task lane already exists.",
            scenario=(
                "TASK: task-2222\n"
                "status=pending\n"
                "priority=P1\n"
                "ready=yes\n"
                "objective=Fix heartbeat event ordering bug.\n"
                "active_same_task_lane=yes\n"
                "lane_status=running\n"
                "lane_note=Specialist already editing backend/app/api/persona/stream.py.\n"
                "cleanup_status=clean\n"
                "recommended_next_step=monitor existing lane rather than dispatch duplicate work.\n"
            ),
            expected={
                "case_id": "same_task_overlap",
                "primary_action": "monitor",
                "should_dispatch": False,
                "should_close": False,
            },
        ),
        JennyBenchmarkCase(
            case_id="same_task_recent_progress",
            name="Same Task Recent Progress",
            description="Do not interrupt active same-task work that still shows fresh progress.",
            scenario=(
                "TASK: task-2223\n"
                "status=pending\n"
                "priority=P1\n"
                "ready=yes\n"
                "objective=Finish a multi-file backend refactor already underway.\n"
                "active_same_task_lane=yes\n"
                "lane_status=running\n"
                "lane_recent_progress=yes\n"
                "lane_note=Specialist committed visible progress 6 minutes ago and latest summary says the work is still in flight.\n"
                "question=Should Jenny redispatch or reconcile this long-running task now?\n"
            ),
            expected={
                "case_id": "same_task_recent_progress",
                "primary_action": "monitor",
                "should_dispatch": False,
                "should_close": False,
            },
            required_summary_terms=("progress", "monitor"),
        ),
        JennyBenchmarkCase(
            case_id="cleanup_blocks_closeout",
            name="Cleanup Blocks Closeout",
            description="Do not declare completion while repo cleanup is still pending.",
            scenario=(
                "TASK: task-3333\n"
                "status=completed\n"
                "quality_gates=passed\n"
                "cleanup_status=CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=0 prunable=0\n"
                "cleanup_note=task-3333 review worktree still exists and must be cleaned first.\n"
                "question=Should Jenny close out the task now?\n"
            ),
            expected={
                "case_id": "cleanup_blocks_closeout",
                "primary_action": "block",
                "should_dispatch": False,
                "should_close": False,
            },
        ),
        JennyBenchmarkCase(
            case_id="session_patience_quiet",
            name="Quiet Session Patience",
            description="Wait on a quiet-but-healthy session instead of prematurely reconciling it.",
            scenario=(
                "SESSION: sess-4444\n"
                "health=active\n"
                "status=waiting_for_model\n"
                "quiet_for_seconds=240\n"
                "last_event_type=assistant_message\n"
                "stall_reason=\n"
                "explicit_termination_signal=no\n"
                "question=Should Jenny reconcile this as stalled right now?\n"
            ),
            expected={
                "case_id": "session_patience_quiet",
                "primary_action": "wait",
                "should_dispatch": False,
                "should_close": False,
            },
        ),
        JennyBenchmarkCase(
            case_id="session_patience_recent_progress",
            name="Recent Progress Patience",
            description="Maintain patience on a long-running session that still shows fresh progress.",
            scenario=(
                "SESSION: sess-4445\n"
                "health=active\n"
                "status=running_tool\n"
                "quiet_for_seconds=150\n"
                "last_event_type=tool_result\n"
                "recent_progress=yes\n"
                "progress_note=The agent finished a tool call 2.5 minutes ago and is now composing the next step.\n"
                "explicit_termination_signal=no\n"
                "question=Should Jenny reconcile or redispatch this long-running session right now?\n"
            ),
            expected={
                "case_id": "session_patience_recent_progress",
                "primary_action": "wait",
                "should_dispatch": False,
                "should_close": False,
            },
            required_summary_terms=("progress", "wait"),
        ),
        JennyBenchmarkCase(
            case_id="stalled_session_reconcile",
            name="Stalled Session Reconcile",
            description="Reconcile a genuinely stalled session instead of waiting indefinitely.",
            scenario=(
                "SESSION: sess-5555\n"
                "health=stalled\n"
                "status=running_tool\n"
                "quiet_for_seconds=1420\n"
                "last_event_type=tool_use\n"
                "stall_reason=no heartbeat for 23 minutes\n"
                "explicit_termination_signal=no\n"
                "question=What should Jenny do next?\n"
            ),
            expected={
                "case_id": "stalled_session_reconcile",
                "primary_action": "reconcile",
                "should_dispatch": False,
                "should_close": False,
            },
        ),
        JennyBenchmarkCase(
            case_id="workspace_inspection_gate",
            name="Workspace Inspection Gate",
            description="Use tools to inspect benchmark files before making a dispatch or closeout call.",
            scenario=(
                "Inspect task.txt, cleanup.txt, and sessions.txt in the current working directory.\n"
                "Then decide what Jenny should do next.\n"
            ),
            expected={
                "case_id": "workspace_inspection_gate",
                "primary_action": "block",
                "should_dispatch": False,
                "should_close": False,
            },
            require_tool_call=True,
            max_turns=8,
            execute_tools=True,
            fixture_files={
                "task.txt": (
                    "TASK: task-6666\n"
                    "status=completed\n"
                    "ready=yes\n"
                    "objective=Ship benchmark report UI polish.\n"
                    "done_when=UI merged and checks passed.\n"
                ),
                "cleanup.txt": (
                    "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=0 prunable=0\n"
                    "agent-hub worktrees:1 dirty:0 orphan:0 prunable:0 tasks:task-6666 review:task-6666\n"
                ),
                "sessions.txt": (
                    "active_persona_sessions=0\n"
                    "active_same_task_lane=no\n"
                    "recent_summary=Task is technically complete but cleanup still pending.\n"
                ),
            },
        ),
        JennyBenchmarkCase(
            case_id="precision_search_architecture",
            name="Precision Search Architecture",
            description="Choose the DRY shared-tool rollout plan for Precision Code Search.",
            scenario=(
                "TASK: task-7777\n"
                "status=pending\n"
                "priority=P1\n"
                "ready=yes\n"
                "objective=Wire Precision Code Search into the shared Agent Hub completion/tooling path.\n"
                "architecture_review=Use shared tool_router/tool_handlers/core path, existing session tool events for telemetry, "
                "a lightweight soft reminder, and keep rg first for workflow/meta text.\n"
                "anti_pattern=Do not create a separate service, new analytics subsystem, classifier model, or hard enforcement first.\n"
                "validated_prework=Codex capability/docs drift already fixed in commits 764ef0ed and b123fff9.\n"
                "recommended_order=1) shared tool 2) soft reminder 3) session-event telemetry 4) mandate text last.\n"
                "question=What should Jenny do next?\n"
            ),
            expected={
                "case_id": "precision_search_architecture",
                "primary_action": "dispatch",
                "should_dispatch": True,
                "should_close": False,
            },
            required_summary_terms=("shared", "soft", "telemetry"),
        ),
        JennyBenchmarkCase(
            case_id="precision_search_live_lookup",
            name="Precision Search Live Lookup",
            description="Use the real precision_code_search tool to verify shared tool wiring before deciding.",
            scenario=(
                "Use precision_code_search to verify whether the real `precision_code_search` tool is already wired "
                "into Agent Hub's shared standard tool path for Jenny/persona.\n"
                "You are deciding whether Jenny should dispatch follow-on adoption/guardrail work now, or block "
                "because the core shared tool does not exist yet.\n"
                "Focus your lookup on where the tool is defined and where it is registered for shared/persona use.\n"
                "If the shared tool is already wired, Jenny should dispatch follow-on work rather than re-implementing the tool.\n"
            ),
            expected={
                "case_id": "precision_search_live_lookup",
                "primary_action": "dispatch",
                "should_dispatch": True,
                "should_close": False,
            },
            required_tool_names=("precision_code_search",),
            max_turns=8,
            execute_tools=True,
            required_summary_terms=("shared",),
            required_project_id="agent-hub",
        ),
        JennyBenchmarkCase(
            case_id="review_request_routes_to_reviewer",
            name="Review Request Routes To Reviewer",
            description="Route review-only work to review workflow instead of code production.",
            scenario=(
                "TASK: task-8888\n"
                "status=pending\n"
                "priority=P1\n"
                "ready=yes\n"
                "request_type=review\n"
                "objective=Review an already-completed change for bugs, regressions, and missing tests.\n"
                "constraints=Do not write code. Findings-first review is required.\n"
                "recommended_next_step=dispatch a review specialist rather than a coder.\n"
            ),
            expected={
                "case_id": "review_request_routes_to_reviewer",
                "primary_action": "dispatch",
                "should_dispatch": True,
                "should_close": False,
            },
            required_summary_terms=("review", "findings"),
        ),
        JennyBenchmarkCase(
            case_id="dead_code_cleanup_followthrough",
            name="Dead Code Cleanup Followthrough",
            description="Do not leave newly discovered dead code behind when the fix is already in scope.",
            scenario=(
                "TASK: task-9999\n"
                "status=pending\n"
                "priority=P1\n"
                "ready=yes\n"
                "objective=Finish a serializer cleanup already underway.\n"
                "during_fix=The specialist found an unused compatibility shim and orphaned fields in the same module.\n"
                "constraint=Clean them up in the same slice rather than leaving 'harmless' leftovers.\n"
                "recommended_next_step=dispatch follow-through work that removes the dead code now.\n"
            ),
            expected={
                "case_id": "dead_code_cleanup_followthrough",
                "primary_action": "dispatch",
                "should_dispatch": True,
                "should_close": False,
            },
            required_summary_terms=("dead", "cleanup"),
        ),
        JennyBenchmarkCase(
            case_id="feedback_triage_hotspot",
            name="Feedback Triage Hotspot",
            description="Use feedback tooling and reconcile a repeated feedback-triage miss.",
            scenario=(
                "Use manage_feedback before answering.\n"
                "HEARTBEAT_FAILURE: The last 3 heartbeat retrospectives all reported that open feedback items "
                "were visible in context but triage still did not happen.\n"
                "correct_layer=Jenny's recurring operating checklist, not a new project task.\n"
                "question=Should Jenny dispatch new work right now, or reconcile her operating model first?\n"
            ),
            expected={
                "case_id": "feedback_triage_hotspot",
                "primary_action": "reconcile",
                "should_dispatch": False,
                "should_close": False,
            },
            required_tool_names=("manage_feedback",),
            max_turns=8,
            execute_tools=True,
            required_summary_terms=("feedback", "triage"),
        ),
        JennyBenchmarkCase(
            case_id="performance_review_honing",
            name="Performance Review Honing",
            description="Inspect performance history plus heartbeat instructions before deciding to self-correct.",
            scenario=(
                "Use review_agent_performance and read_heartbeat_instructions before answering.\n"
                "BENCHMARK_SIGNAL: Two consecutive evaluation runs showed repeated misses on tool-required "
                "governance cases.\n"
                "correct_layer=Jenny's own operating model, observability habits, or model assignment.\n"
                "question=Should Jenny dispatch project work now, or reconcile her heartbeat/performance loop first?\n"
            ),
            expected={
                "case_id": "performance_review_honing",
                "primary_action": "reconcile",
                "should_dispatch": False,
                "should_close": False,
            },
            required_tool_names=("review_agent_performance", "read_heartbeat_instructions"),
            max_turns=8,
            execute_tools=True,
            required_summary_terms=("heartbeat", "performance"),
        ),
        JennyBenchmarkCase(
            case_id="model_config_reconsideration",
            name="Model Config Reconsideration",
            description="Inspect benchmarks/performance before deciding whether Jenny should revisit her model setup.",
            scenario=(
                "Use manage_model_config and review_agent_performance before answering.\n"
                "OBSERVATION: Fresh benchmark data exists, and the current primary model is the only one repeatedly "
                "missing tool-heavy governance cases while another configured model succeeds.\n"
                "correct_layer=Model assignment review before more dispatching.\n"
                "question=Should Jenny reconcile model selection now?\n"
            ),
            expected={
                "case_id": "model_config_reconsideration",
                "primary_action": "reconcile",
                "should_dispatch": False,
                "should_close": False,
            },
            required_tool_names=("manage_model_config", "review_agent_performance"),
            max_turns=8,
            execute_tools=True,
            required_summary_terms=("model", "benchmark"),
        ),
    ]


def get_case_by_id(case_id: str) -> JennyBenchmarkCase:
    """Resolve a benchmark case by id."""
    for case in get_jenny_benchmark_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown Jenny benchmark case: {case_id}")


def prepare_case_workspace(case: JennyBenchmarkCase, workdir: Path) -> Path:
    """Materialize any fixture files required for a benchmark case."""
    workdir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in case.fixture_files.items():
        destination = workdir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    return workdir
