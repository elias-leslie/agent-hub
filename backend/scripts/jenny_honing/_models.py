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


@dataclass
class _LoopState:
    """Mutable state threaded through honing loop iterations."""

    iterations: list[JennyHoningIteration] = field(default_factory=list)
    honed: bool = False
    previous_best_score: float | None = None
    previous_failing_attempts: int | None = None
    previous_clusters: list[dict[str, Any]] | None = None

    def to_result(self) -> dict[str, Any]:
        return {
            "iterations": [r.to_dict() for r in self.iterations],
            "completed_iterations": len(self.iterations),
            "honed": self.honed,
        }
