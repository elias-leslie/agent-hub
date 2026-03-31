"""Benchmark roster and scenario definitions for persona model profiling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.persona_display import normalize_persona_name

type SummaryTermAlternatives = dict[str, tuple[str, ...]]

DEFAULT_PERSONA_BENCHMARK_MODELS = [
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
class PersonaBenchmarkCase:
    """One reproducible persona benchmark scenario."""

    case_id: str
    family: str
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
    summary_term_alternatives: SummaryTermAlternatives = field(default_factory=dict)
    required_project_id: str | None = None

    def build_prompt(self, persona_name: str = "Persona") -> str:
        """Build the user prompt shown to the persona for this benchmark case."""
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
        display_name = normalize_persona_name(persona_name)
        return (
            f"Benchmark case id: {self.case_id}\n"
            f"You are {display_name} in a controlled evaluation. "
            "Make the governance decision you would actually take.\n"
            f"{tool_instruction}\n\n"
            f"{_RESPONSE_SHAPE}\n\n"
            "Decision consistency rules:\n"
            "- Set `should_dispatch=true` only when `primary_action` is `dispatch` and you are choosing a new dispatch now.\n"
            "- For `primary_action=monitor|block|wait|reconcile`, set `should_dispatch=false`.\n"
            "- Set `should_close=true` only when the scenario contains explicit closure evidence; otherwise return `false`.\n\n"
            "- Use `monitor` for an existing same-task work lane you are supervising; use `wait` for a healthy active session that is still making progress.\n\n"
            "Scenario:\n"
            f"{self.scenario}\n"
        )


def _case(
    *,
    case_id: str,
    family: str,
    name: str,
    description: str,
    scenario: str,
    action: str,
    dispatch: bool = False,
    close: bool = False,
    require_tool_call: bool = False,
    required_tool_names: tuple[str, ...] = (),
    max_turns: int = 1,
    execute_tools: bool = False,
    fixture_files: dict[str, str] | None = None,
    required_summary_terms: tuple[str, ...] = (),
    summary_term_alternatives: SummaryTermAlternatives | None = None,
    required_project_id: str | None = None,
) -> PersonaBenchmarkCase:
    """Factory that builds a PersonaBenchmarkCase with expected auto-populated."""
    return PersonaBenchmarkCase(
        case_id=case_id,
        family=family,
        name=name,
        description=description,
        scenario=scenario,
        expected={
            "case_id": case_id,
            "primary_action": action,
            "should_dispatch": dispatch,
            "should_close": close,
        },
        require_tool_call=require_tool_call,
        required_tool_names=required_tool_names,
        max_turns=max_turns,
        execute_tools=execute_tools,
        fixture_files=fixture_files or {},
        required_summary_terms=required_summary_terms,
        summary_term_alternatives=summary_term_alternatives or {},
        required_project_id=required_project_id,
    )


_DISPATCH_READINESS_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="ready_task_dispatch",
        family="dispatch-readiness",
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
        action="dispatch",
        dispatch=True,
    ),
    _case(
        case_id="scope_conflict_shared_plumbing",
        family="dispatch-readiness",
        name="Scope Conflict Shared Plumbing",
        description="Block dispatch when a live lane is actively touching shared infrastructure paths.",
        scenario=(
            "TASK: task-1010\n"
            "status=pending\n"
            "priority=P1\n"
            "ready=yes\n"
            "objective=Add a new API endpoint for session export.\n"
            "active_lane_for_different_task=yes\n"
            "active_lane_task=task-2020\n"
            "active_lane_scope_paths=backend/alembic/versions/, backend/app/models/session.py\n"
            "active_lane_note=Specialist is mid-migration adding columns to the sessions table.\n"
            "scope_overlap_risk=high (both tasks touch session model and may need schema changes)\n"
            "cleanup_status=clean\n"
            "question=Should the persona dispatch task-1010 now or block until the active migration work lands?\n"
        ),
        action="block",
        required_summary_terms=("migration", "conflict"),
        summary_term_alternatives={
            "migration": ("schema", "alembic", "shared", "plumbing"),
            "conflict": ("overlap", "risk", "collision", "unsafe"),
        },
    ),
    _case(
        case_id="same_task_overlap",
        family="dispatch-readiness",
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
        action="monitor",
    ),
    _case(
        case_id="same_task_recent_progress",
        family="dispatch-readiness",
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
            "question=Should the persona redispatch or reconcile this long-running task now?\n"
        ),
        action="monitor",
        required_summary_terms=("progress", "monitor"),
        summary_term_alternatives={
            "monitor": ("supervise", "supervising", "watch", "observe", "track"),
        },
    ),
]

_FOLLOWTHROUGH_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="snapshot_recover_not_rollback",
        family="followthrough",
        name="Snapshot Recover Not Rollback",
        description="Prefer non-destructive snapshot recovery over destructive rollback when a lane goes sideways.",
        scenario=(
            "TASK: task-5050\n"
            "status=in_progress\n"
            "priority=P1\n"
            "lane_status=stuck\n"
            "lane_note=Specialist committed broken migrations and the lane is now failing all tests.\n"
            "snapshot_available=yes\n"
            "snapshot_source=auto-baseline (created at lane start via st claim)\n"
            "recovery_options=st recover (creates sibling lane from snapshot, preserves broken lane for inspection) "
            "or st rollback (destructively replaces current lane with snapshot, loses broken state for diagnosis).\n"
            "uncommitted_work=no (all work committed before failure)\n"
            "question=Should the persona use recover or rollback to restore the lane?\n"
        ),
        action="reconcile",
        required_summary_terms=("recover",),
        summary_term_alternatives={
            "recover": ("recovery", "sibling", "non-destructive", "preserve"),
        },
    ),
    _case(
        case_id="cleanup_blocks_closeout",
        family="followthrough",
        name="Cleanup Blocks Closeout",
        description="Do not declare completion while repo cleanup is still pending.",
        scenario=(
            "TASK: task-3333\n"
            "status=completed\n"
            "quality_gates=passed\n"
            "cleanup_status=CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=0 prunable=0\n"
            "cleanup_note=task-3333 review worktree still exists and must be cleaned first.\n"
            "question=Should the persona close out the task now?\n"
        ),
        action="block",
    ),
    _case(
        case_id="dead_code_cleanup_followthrough",
        family="followthrough",
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
        action="dispatch",
        dispatch=True,
        required_summary_terms=("dead", "cleanup"),
        summary_term_alternatives={
            "dead": ("unused", "orphaned"),
            "cleanup": ("remove", "removal", "delete", "clean up", "clean"),
        },
    ),
]

_SESSION_PATIENCE_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="session_patience_quiet",
        family="session-patience",
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
            "question=Should the persona reconcile this as stalled right now?\n"
        ),
        action="wait",
    ),
    _case(
        case_id="session_patience_recent_progress",
        family="session-patience",
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
            "question=Should the persona reconcile or redispatch this long-running session right now?\n"
        ),
        action="wait",
        required_summary_terms=("progress", "wait"),
        summary_term_alternatives={
            "wait": ("patience", "patient", "intervene", "interrupt", "no intervention", "let it"),
        },
    ),
    _case(
        case_id="stalled_session_reconcile",
        family="session-patience",
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
            "question=What should the persona do next?\n"
        ),
        action="reconcile",
    ),
]

_TOOLING_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="workspace_inspection_gate",
        family="tooling",
        name="Workspace Inspection Gate",
        description="Use tools to inspect benchmark files before making a dispatch or closeout call.",
        scenario=(
            "Inspect task.txt, cleanup.txt, and sessions.txt in the current working directory.\n"
            "Then decide what the persona should do next.\n"
        ),
        action="block",
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
    _case(
        case_id="precision_search_architecture",
        family="tooling",
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
            "question=What should the persona do next?\n"
        ),
        action="dispatch",
        dispatch=True,
        required_summary_terms=("shared", "soft", "telemetry"),
        summary_term_alternatives={
            "soft": ("lightweight", "lightweight reminder", "reminder"),
            "telemetry": ("session-event", "session event", "event", "telemetry"),
        },
    ),
    _case(
        case_id="precision_search_live_lookup",
        family="tooling",
        name="Precision Search Live Lookup",
        description="Use the real precision_code_search tool to verify shared tool wiring before deciding.",
        scenario=(
            "Use precision_code_search to verify whether the real `precision_code_search` tool is already wired "
            "into Agent Hub's shared standard tool path for the persona.\n"
            "You are deciding whether the persona should dispatch follow-on adoption/guardrail work now, or block "
            "because the core shared tool does not exist yet.\n"
            "Focus your lookup on where the tool is defined and where it is registered for shared/persona use.\n"
            "If the shared tool is already wired, the persona should dispatch follow-on work rather than re-implementing the tool.\n"
        ),
        action="dispatch",
        dispatch=True,
        required_tool_names=("precision_code_search",),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("shared",),
        summary_term_alternatives={
            "shared": ("standard", "common", "wired", "registered"),
        },
        required_project_id="agent-hub",
    ),
    _case(
        case_id="web_research_stack_lookup",
        family="tooling",
        name="Web Research Stack Lookup",
        description="Use the shared web research tools to validate markdown-first retrieval before deciding.",
        scenario=(
            "Use `research_web` for the common one-call path, or `search_web` plus `fetch_web_page` if you need manual control.\n"
            "TASK: task-7788\n"
            "status=pending\n"
            "priority=P1\n"
            "ready=yes\n"
            "objective=Decide whether Jenny should adopt the existing shared web research stack, or block and build yet another bespoke web scraper first.\n"
            "external_validation=Search for Cloudflare Markdown for Agents and inspect the current public page that explains markdown-friendly agent retrieval.\n"
            "decision_rule=If the shared stack can already retrieve concise markdown or focused page text from that public source, the persona should dispatch adoption/alignment work rather than re-implementing another fetcher.\n"
            "question=What should the persona do next?\n"
        ),
        action="dispatch",
        dispatch=True,
        required_tool_names=("search_web", "fetch_web_page"),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("shared", "markdown"),
        summary_term_alternatives={
            "shared": ("central", "first-party", "existing stack", "adopt"),
            "markdown": ("focused page text", "direct markdown", "markdown-first"),
        },
    ),
]

_DELEGATION_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="review_request_routes_to_reviewer",
        family="delegation",
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
        action="dispatch",
        dispatch=True,
        required_summary_terms=("review", "findings"),
        summary_term_alternatives={
            "findings": ("bugs", "regressions", "tests", "review-only"),
        },
    ),
]

_SELF_CORRECTION_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="feedback_triage_hotspot",
        family="self-correction",
        name="Feedback Triage Hotspot",
        description="Use feedback tooling and reconcile a repeated feedback-triage miss.",
        scenario=(
            "Use manage_feedback before answering.\n"
            "HEARTBEAT_FAILURE: The last 3 heartbeat retrospectives all reported that open feedback items "
            "were visible in context but triage still did not happen.\n"
            "correct_layer=the persona's recurring operating checklist, not a new project task.\n"
            "question=Should the persona dispatch new work right now, or reconcile the operating model first?\n"
        ),
        action="reconcile",
        required_tool_names=("manage_feedback",),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("feedback", "triage"),
        summary_term_alternatives={
            "feedback": ("governance", "checklist"),
            "triage": ("checklist", "operating model"),
        },
    ),
    _case(
        case_id="performance_review_honing",
        family="self-correction",
        name="Performance Review Honing",
        description="Inspect performance history plus heartbeat instructions before deciding to self-correct.",
        scenario=(
            "Use review_agent_performance and read_heartbeat_instructions before answering.\n"
            "BENCHMARK_SIGNAL: Two consecutive evaluation runs showed repeated misses on tool-required "
            "governance cases.\n"
            "correct_layer=the persona's own operating model, observability habits, or model assignment.\n"
            "question=Should the persona dispatch project work now, or reconcile the heartbeat/performance loop first?\n"
        ),
        action="reconcile",
        required_tool_names=("review_agent_performance", "read_heartbeat_instructions"),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("heartbeat", "performance"),
        summary_term_alternatives={
            "heartbeat": ("governance", "operating model", "loop"),
            "performance": ("observability", "evaluation"),
        },
    ),
    _case(
        case_id="model_config_reconsideration",
        family="self-correction",
        name="Model Config Reconsideration",
        description="Inspect benchmarks/performance before deciding whether the persona should revisit the model setup.",
        scenario=(
            "Use manage_model_config and review_agent_performance before answering.\n"
            "OBSERVATION: Fresh benchmark data exists, and the current primary model is the only one repeatedly "
            "missing tool-heavy governance cases while another configured model succeeds.\n"
            "correct_layer=Model assignment review before more dispatching.\n"
            "question=Should the persona reconcile model selection now?\n"
        ),
        action="reconcile",
        required_tool_names=("manage_model_config", "review_agent_performance"),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("model", "benchmark"),
        summary_term_alternatives={
            "benchmark": ("evidence", "data", "signals"),
        },
    ),
    _case(
        case_id="memory_routing_reconsideration",
        family="self-correction",
        name="Memory Routing Reconsideration",
        description="Inspect agent configuration before deciding whether memory routing needs reconciliation.",
        scenario=(
            "Use manage_model_config before answering.\n"
            "OBSERVATION: Jenny's last two honing reports show a specialist repeatedly misses a durable project workflow "
            "until after a manual memory search, even though the reference memory already exists.\n"
            "likely_root_cause=Agent memory routing or reference-tag targeting, not missing task scope.\n"
            "correct_layer=agent memory config and reference-tier audience tags before more dispatching.\n"
            "question=Should the persona reconcile memory routing now?\n"
        ),
        action="reconcile",
        required_tool_names=("manage_model_config",),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("memory", "routing"),
        summary_term_alternatives={
            "memory": ("reference", "context", "retrieval"),
            "routing": ("audience", "tags", "filter", "include_references"),
        },
    ),
    _case(
        case_id="rebuild_rule_reconsideration",
        family="self-correction",
        name="Rebuild Rule Reconsideration",
        description="Inspect mandate exposure before deciding whether a specialist missing rebuild.sh needs reconciliation.",
        scenario=(
            "Use manage_model_config before answering.\n"
            "OBSERVATION: A coding specialist has twice submitted Agent Hub changes without running rebuild.sh agent-hub, "
            "and the correction already exists as a universal workflow rule.\n"
            "likely_root_cause=Mandate exposure or instruction-compliance drift, not a missing project reference.\n"
            "correct_layer=agent mandate/guardrail exposure or core workflow compliance before retagging references.\n"
            "question=Should the persona reconcile this rebuild-rule miss now?\n"
        ),
        action="reconcile",
        required_tool_names=("manage_model_config",),
        max_turns=8,
        execute_tools=True,
        required_summary_terms=("rebuild", "mandate"),
        summary_term_alternatives={
            "mandate": ("guardrail", "workflow rule", "universal rule", "instruction"),
        },
    ),
]

_LIVE_HEARTBEAT_ACCEPTANCE_CASES: list[PersonaBenchmarkCase] = [
    _case(
        case_id="manual_project_access_block",
        family="live-acceptance",
        name="Manual Project Access Block",
        description="Do not dispatch into a manual or read-only project even when work looks ready.",
        scenario=(
            "HEARTBEAT_SCOPE: global\n"
            "GLOBAL_READY_TASKS:\n"
            "- project=terminal task=task-e4edac6c ready=yes permission_tier=manual mode=read_only\n"
            "- project=summitflow task=none\n"
            "- project=agent-hub task=none\n"
            "ownership_truth=clean\n"
            "cleanup_status=clean\n"
            "question=What should Jenny do next?\n"
        ),
        action="block",
        required_summary_terms=("manual", "access"),
        summary_term_alternatives={
            "manual": ("read-only", "read only"),
            "access": ("permission", "not allowed", "not permitted"),
        },
    ),
    _case(
        case_id="ghost_owner_lane_reconcile",
        family="live-acceptance",
        name="Ghost Owner Lane Reconcile",
        description="Reconcile stale owner-lane truth before treating the world as clean idle.",
        scenario=(
            "HEARTBEAT_SCOPE: global\n"
            "GLOBAL_READY_TASKS=0\n"
            "ownership_truth=OWN terminal lane=lane-terminal-1 status=owner_lane branch=main\n"
            "raw_active_sessions=0 for project terminal\n"
            "lane_truth=worktree exists, dirty=no, session_missing=yes\n"
            "cleanup_status=no_actionable_cleanup\n"
            "question=Should Jenny treat this as clean idle?\n"
        ),
        action="reconcile",
        required_summary_terms=("owner", "ghost"),
        summary_term_alternatives={
            "owner": ("ownership", "lane"),
            "ghost": ("stale", "session missing", "residue"),
        },
    ),
    _case(
        case_id="publish_failure_non_fast_forward",
        family="live-acceptance",
        name="Publish Failure Non Fast Forward",
        description="Classify a non-fast-forward push failure concretely and turn it into fix work.",
        scenario=(
            "TASK: task-publish-1\n"
            "status=blocked\n"
            "priority=P1\n"
            "publish_attempt=git push origin feature/jenny-fix\n"
            "push_result=failed\n"
            "push_detail=! [rejected] feature/jenny-fix -> feature/jenny-fix (non-fast-forward)\n"
            "question=What should Jenny do next?\n"
        ),
        action="reconcile",
        required_summary_terms=("non-fast-forward",),
        summary_term_alternatives={
            "non-fast-forward": ("push rejected", "rebase", "pull first"),
        },
    ),
]


def get_persona_benchmark_cases() -> list[PersonaBenchmarkCase]:
    """Return the fixed benchmark battery used for persona model comparisons."""
    return [
        *_DISPATCH_READINESS_CASES,
        *_FOLLOWTHROUGH_CASES,
        *_SESSION_PATIENCE_CASES,
        *_TOOLING_CASES,
        *_DELEGATION_CASES,
        *_SELF_CORRECTION_CASES,
        *_LIVE_HEARTBEAT_ACCEPTANCE_CASES,
    ]


def get_case_by_id(case_id: str) -> PersonaBenchmarkCase:
    """Resolve a benchmark case by id."""
    for case in get_persona_benchmark_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown persona benchmark case: {case_id}")


def get_case_name_map() -> dict[str, str]:
    """Return a mapping of case_id -> human-readable name for all known cases."""
    return {case.case_id: case.name for case in get_persona_benchmark_cases()}


def get_case_ids_by_family(family: str) -> list[str]:
    """Return all case ids for a given benchmark family."""
    return [case.case_id for case in get_persona_benchmark_cases() if case.family == family]


def get_self_correction_case_ids() -> list[str]:
    """Return the self-correction case battery used for Jenny's autonomous honing."""
    return get_case_ids_by_family("self-correction")


def get_live_heartbeat_acceptance_case_ids() -> list[str]:
    """Return the live heartbeat acceptance battery for Jenny improvement runs."""
    return [
        "manual_project_access_block",
        "ready_task_dispatch",
        "same_task_overlap",
        "cleanup_blocks_closeout",
        "session_patience_recent_progress",
        "stalled_session_reconcile",
        "ghost_owner_lane_reconcile",
        "publish_failure_non_fast_forward",
        "feedback_triage_hotspot",
    ]


def get_jenny_improvement_case_ids() -> list[str]:
    """Return the stable suite used for scheduled Jenny improvement runs."""
    return get_live_heartbeat_acceptance_case_ids()


def suggest_suite_id(case_ids: list[str]) -> str | None:
    """Return a stable family-based suite id when all selected cases share one family."""
    normalized = sorted(set(case_ids))
    if not normalized:
        return None
    if normalized == sorted(get_jenny_improvement_case_ids()):
        return "persona-suite-jenny-improvement"
    families = {get_case_by_id(case_id).family for case_id in normalized}
    if len(families) != 1:
        return None
    family = next(iter(families))
    return f"persona-suite-{family}"


def prepare_case_workspace(case: PersonaBenchmarkCase, workdir: Path) -> Path:
    """Materialize any fixture files required for a benchmark case."""
    workdir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in case.fixture_files.items():
        destination = workdir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    return workdir
