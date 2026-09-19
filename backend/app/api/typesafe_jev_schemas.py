"""Typed request and response contract for the bounded TypeSafe Jev pilot."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

JEV_MODEL_ID = "jev-1.13.0"
JEV_PRICING_CONTRACT = "jev-1.13.0:usd-0.042-per-million-input:2026-09-19"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoulQuestion(StrictModel):
    type: Literal["noul"]
    instructions: JsonValue
    criteria: dict[Literal["true", "false"], JsonValue] | None = None


class ChoiceQuestion(StrictModel):
    type: Literal["choice"]
    instructions: JsonValue
    criteria: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_cardinality(self) -> ChoiceQuestion:
        if not 2 <= len(self.criteria) <= 255:
            raise ValueError("choice criteria must contain 2 to 255 options")
        return self


class ScoreQuestion(StrictModel):
    type: Literal["score"]
    instructions: JsonValue
    criteria: list[JsonValue]

    @model_validator(mode="after")
    def validate_cardinality(self) -> ScoreQuestion:
        if not 2 <= len(self.criteria) <= 10:
            raise ValueError("score criteria must contain 2 to 10 ordered levels")
        return self


JevQuestion = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class SourceProvenance(StrictModel):
    source_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RubricProvenance(StrictModel):
    rubric_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObservationProvenance(StrictModel):
    series_id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    purpose: str = Field(min_length=1)


class SystemOneRequest(StrictModel):
    """Reusable typed transport, without a pilot budget or ledger identity."""
    state: JsonValue
    questions: dict[str, JevQuestion] = Field(min_length=1)
    model: str = Field(min_length=1)


class TypeSafeJevRequest(StrictModel):
    request_id: UUID
    state: JsonValue
    questions: dict[str, JevQuestion] = Field(min_length=1)
    sources: list[SourceProvenance] = Field(min_length=1)
    rubric: RubricProvenance
    observation: ObservationProvenance | None = None
    model: Literal["jev-1.13.0"] = JEV_MODEL_ID
    pricing_contract: Literal[
        "jev-1.13.0:usd-0.042-per-million-input:2026-09-19"
    ] = JEV_PRICING_CONTRACT
    dry_run: bool = False


class JevUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class NoulAnswer(StrictModel):
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class ChoiceAnswer(StrictModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)


class ScoreAnswer(StrictModel):
    type: Literal["score"]
    score: float
    legend: dict[str, JsonValue]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)


JevAnswer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class TypeSafeProviderResponse(StrictModel):
    model: str
    answers: dict[str, JevAnswer]
    usage: JevUsage


class JevBudgetView(StrictModel):
    ceiling_usd: str
    spent_usd: str
    reserved_usd: str
    available_usd: str
    reservation_usd: str


class TypeSafeJevResult(StrictModel):
    request_id: UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["dry_run", "reserved", "succeeded", "failed", "uncertain"]
    deduplicated: bool = False
    model_requested: str
    model_observed: str | None = None
    pricing_contract: str
    provider_request_id: str | None = None
    usage: JevUsage | None = None
    answers: dict[str, JevAnswer] | None = None
    budget: JevBudgetView
    sources: list[SourceProvenance]
    rubric: RubricProvenance
    observation: ObservationProvenance | None = None
    error_kind: str | None = None
    error_detail: str | None = None
