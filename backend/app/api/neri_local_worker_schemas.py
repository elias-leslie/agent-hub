"""Wire contracts for Neri's bounded local-model candidate worker."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NeriLocalTaskFamily(StrEnum):
    FACTS_UNKNOWNS = "facts_unknowns"
    EVIDENCE_CONSISTENCY = "evidence_consistency"
    SCOPE_POLICY_PARSE = "scope_policy_parse"
    EVIDENCE_CONDENSATION = "evidence_condensation"
    MATRIX_CONSTRUCTION = "matrix_construction"
    HYPOTHESIS_CONTROLS = "hypothesis_controls"
    CANDIDATE_TRIAGE = "candidate_triage"
    LEARNING_DRAFT = "learning_draft"


class NeriHarnessArm(StrEnum):
    BARE_SCHEMA = "bare_schema"
    ROLE_CHECKLIST = "role_checklist"
    GROUNDED_DECOMPOSITION = "grounded_decomposition"
    CRITIQUE_REPAIR = "critique_repair"


class NeriPacketEvidence(_StrictModel):
    ref: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    content: str = Field(min_length=1, max_length=12_000)


class NeriLocalWorkerPacket(_StrictModel):
    objective: str = Field(min_length=1, max_length=1_000)
    evidence: list[NeriPacketEvidence] = Field(min_length=1, max_length=64)
    constraints: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("constraints must contain 1-500 character strings")
        return values

    @model_validator(mode="after")
    def validate_packet(self) -> NeriLocalWorkerPacket:
        refs = [item.ref for item in self.evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("evidence refs must be unique")
        if len(self.model_dump_json()) > 65_536:
            raise ValueError("serialized packet exceeds 65,536 characters")
        return self


class NeriLocalWorkerItem(_StrictModel):
    kind: Literal[
        "fact",
        "unknown",
        "conflict",
        "missing_evidence",
        "risk",
        "control",
        "hypothesis",
        "draft_text",
        "question",
    ]
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=16)
    confidence: Literal["low", "medium", "high"]
    choices: list[str] = Field(default_factory=list, max_length=4)
    answer_index: int | None = Field(default=None, ge=0, le=3)

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("choices must contain 1-500 character strings")
        normalized = [value.strip().casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("choices must be unique")
        return values

    @model_validator(mode="after")
    def validate_answer(self) -> NeriLocalWorkerItem:
        if self.choices and self.answer_index is None:
            raise ValueError("answer_index is required when choices are present")
        if not self.choices and self.answer_index is not None:
            raise ValueError("answer_index requires choices")
        if self.answer_index is not None and self.answer_index >= len(self.choices):
            raise ValueError("answer_index is outside the choices list")
        return self


class NeriLocalWorkerOutput(_StrictModel):
    disposition: Literal["complete", "insufficient_evidence", "refused"]
    summary: str = Field(min_length=1, max_length=2_000)
    items: list[NeriLocalWorkerItem] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("limitations must contain 1-500 character strings")
        return values


class NeriLocalWorkerRequest(_StrictModel):
    task_family: NeriLocalTaskFamily
    harness_arm: NeriHarnessArm = NeriHarnessArm.GROUNDED_DECOMPOSITION
    packet: NeriLocalWorkerPacket
    reasoning_effort: Literal["low", "medium", "xhigh"] = "xhigh"
    max_output_tokens: int = Field(default=4_096, ge=256, le=8_192)


class NeriLocalWorkerExecution(_StrictModel):
    output: NeriLocalWorkerOutput
    model_id: str
    effective_model: str
    provider: str
    task_family: NeriLocalTaskFamily
    harness_arm: NeriHarnessArm
    input_sha256: str
    prompt_revision: int
    evaluation_config: dict[str, Any]
    runtime_profile: dict[str, Any]
    runtime_metrics: dict[str, int | float | str | None]


class NeriLocalWorkerStatus(_StrictModel):
    model_id: str
    lifecycle: str
    endpoint_reachable: bool
    exact_model_loaded: bool
    runtime_profile: dict[str, Any]
    promoted_task_families: list[NeriLocalTaskFamily] = Field(default_factory=list)
    detail: str | None = None


class NeriLocalBenchmarkRequest(_StrictModel):
    split: Literal["development", "locked"] = "development"
    harness_arms: list[NeriHarnessArm] = Field(
        default_factory=lambda: list(NeriHarnessArm), min_length=1, max_length=4
    )
    task_families: list[NeriLocalTaskFamily] | None = Field(default=None, max_length=8)
    runs_per_case: int = Field(default=1, ge=1, le=3)
    reasoning_effort: Literal["low", "medium", "xhigh"] = "xhigh"
    max_output_tokens: int = Field(default=4_096, ge=256, le=8_192)
    persist: bool = True


class NeriLocalBenchmarkResponse(_StrictModel):
    benchmark_id: str
    persisted_run_id: str | None = None
    split: str
    attempts: int
    passed_attempts: int
    infra_failures: int
    average_score: float
    pass_rate: float
    results: list[dict[str, Any]]


__all__ = [
    "NeriHarnessArm",
    "NeriLocalBenchmarkRequest",
    "NeriLocalBenchmarkResponse",
    "NeriLocalTaskFamily",
    "NeriLocalWorkerExecution",
    "NeriLocalWorkerItem",
    "NeriLocalWorkerOutput",
    "NeriLocalWorkerPacket",
    "NeriLocalWorkerRequest",
    "NeriLocalWorkerStatus",
    "NeriPacketEvidence",
]
