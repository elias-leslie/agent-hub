"""Dataclasses for the Jenny honing loop."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JennyHoningIteration:
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JennyMutableState:
    heartbeat_instructions: str
    heartbeat_revision_id: str | None
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    temperature: float
    thinking_level: str | None
    supervisor_primary_model_id: str | None = None
    supervisor_fallback_models: list[str] = field(default_factory=list)
    supervisor_escalation_model_id: str | None = None
    supervisor_temperature: float | None = None
    supervisor_thinking_level: str | None = None
    completion_review_prompt: str | None = None
    completion_review_prompt_revision_id: str | None = None
    completion_review_rules: str | None = None
    completion_review_rules_revision_id: str | None = None


@dataclass
class _LoopState:
    """Mutable state threaded through honing loop iterations."""

    iterations: list[JennyHoningIteration] = field(default_factory=list)
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
