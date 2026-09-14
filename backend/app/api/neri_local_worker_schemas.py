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


class NeriLocalWorkerPassEvidence(_StrictModel):
    pass_number: int = Field(ge=1, le=2)
    validated: bool
    failure_kind: str | None = None
    content: str = Field(max_length=65_536)
    content_sha256: str = Field(min_length=64, max_length=64)
    runtime_metrics: dict[str, int | str | None]


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
    runtime_metrics: dict[str, bool | int | float | str | None]
    pass_evidence: list[NeriLocalWorkerPassEvidence] = Field(min_length=1, max_length=2)


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
    case_ids: list[str] | None = Field(default=None, min_length=1, max_length=32)
    study_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    study_block: int | None = Field(default=None, ge=1, le=8)
    study_case_position: int | None = Field(default=None, ge=1, le=24)
    study_replacement: int = Field(default=0, ge=0, le=3)
    runs_per_case: int = Field(default=1, ge=1, le=3)
    reasoning_effort: Literal["low", "medium", "xhigh"] = "xhigh"
    max_output_tokens: int = Field(default=4_096, ge=256, le=8_192)
    persist: bool = True

    @field_validator("case_ids")
    @classmethod
    def validate_case_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if any(
            not value
            or len(value) > 120
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                for character in value
            )
            for value in values
        ):
            raise ValueError("case_ids must contain 1-120 character identifiers")
        if len(values) != len(set(values)):
            raise ValueError("case_ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_study_binding(self) -> NeriLocalBenchmarkRequest:
        study_fields = (self.study_id, self.study_block, self.study_case_position)
        if any(value is not None for value in study_fields) and any(
            value is None for value in study_fields
        ):
            raise ValueError(
                "study_id, study_block, and study_case_position must be supplied together"
            )
        if self.study_id is not None:
            if self.split != "locked":
                raise ValueError("study mode requires the locked split")
            if self.case_ids is not None or self.task_families is not None:
                raise ValueError("study mode owns exact case and family selection")
            if self.runs_per_case != 1:
                raise ValueError("study mode runs exactly one durable attempt per request")
            if self.harness_arms != [NeriHarnessArm.ROLE_CHECKLIST]:
                raise ValueError("study mode requires exactly the role_checklist harness")
            if not self.persist:
                raise ValueError("study mode requires durable persistence")
        elif self.study_replacement:
            raise ValueError("study_replacement requires study mode")
        return self


class NeriLocalBenchmarkResponse(_StrictModel):
    benchmark_id: str
    persisted_run_id: str | None = None
    split: str
    case_ids: list[str]
    suite_oracle_sha256: str
    study_id: str | None = None
    study_manifest_sha256: str | None = None
    study_block: int | None = None
    study_case_position: int | None = None
    study_replacement: int = 0
    adjudication_label: str | None = None
    preflight_run_id: str | None = None
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
    "NeriLocalWorkerPassEvidence",
    "NeriLocalWorkerRequest",
    "NeriLocalWorkerStatus",
    "NeriPacketEvidence",
]
