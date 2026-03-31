"""Dataclasses and config types for the persona honing loop."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class _IterationConfig(TypedDict):
    models: list[str]
    case_ids: list[str]
    runs_per_case: int
    reviewer_models: list[str] | None
    reviewer_case_ids: list[str] | None
    reviewer_runs_per_case: int
    project_id: str
    working_root: Path
    output_dir: Path
    seed: int
    timeout_seconds: float | None
    client_id: str
    use_memory: bool
    benchmark_task_type: str
    cohort_repetitions: int
    base_url: str
    agent_slug: str
    persist_results: bool
    disable_completion_review: bool


@dataclass
class PersonaHoningIteration:
    """One benchmark + self-improvement cycle."""

    iteration: int
    benchmark_id: str
    top_model: str | None
    top_score: float
    failing_attempts: int
    benchmark_report_path: str | None
    failure_clusters: list[dict[str, Any]] | None = None
    persistent_failure_clusters: list[dict[str, Any]] | None = None
    persisted_run_id: str | None = None
    baseline_run_ids: list[str] | None = None
    candidate_run_ids: list[str] | None = None
    experiment_key: str | None = None
    experiment_summary: dict[str, Any] | None = None
    review_benchmark_id: str | None = None
    review_top_model: str | None = None
    review_top_score: float | None = None
    review_failing_attempts: int | None = None
    review_failure_clusters: list[dict[str, Any]] | None = None
    review_persistent_failure_clusters: list[dict[str, Any]] | None = None
    review_baseline_run_ids: list[str] | None = None
    review_candidate_run_ids: list[str] | None = None
    review_experiment_key: str | None = None
    review_experiment_summary: dict[str, Any] | None = None
    rollback_applied: bool = False
    improvement_session_id: str | None = None
    improvement_tools: list[str] | None = None
    improvement_content: str | None = None
    improvement_parsed: dict[str, Any] | None = None
    field_snapshot: dict[str, Any] | None = None
    final_decision: str | None = None
    final_decision_reason: str | None = None
    final_decision_source: str | None = None
    decision_review: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaMutableState:
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    temperature: float
    thinking_level: str | None
    prompt_states: dict[str, dict[str, str | None]] = field(default_factory=dict)
    supervisor_primary_model_id: str | None = None
    supervisor_fallback_models: list[str] = field(default_factory=list)
    supervisor_escalation_model_id: str | None = None
    supervisor_temperature: float | None = None
    supervisor_thinking_level: str | None = None


@dataclass
class _LoopState:
    """Mutable state threaded through honing loop iterations."""

    iterations: list[PersonaHoningIteration] = field(default_factory=list)
    honed: bool = False
    previous_best_score: float | None = None
    previous_failing_attempts: int | None = None
    previous_clusters: list[dict[str, Any]] | None = None
    previous_review_best_score: float | None = None
    previous_review_failing_attempts: int | None = None
    previous_review_clusters: list[dict[str, Any]] | None = None

    def to_result(self) -> dict[str, Any]:
        return {
            "iterations": [r.to_dict() for r in self.iterations],
            "completed_iterations": len(self.iterations),
            "honed": self.honed,
        }
