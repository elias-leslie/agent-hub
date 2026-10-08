"""Typed request and response contracts for TypeSafe System One."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


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


class SystemOneRequest(StrictModel):
    """State and typed questions for one System One model."""
    state: JsonValue
    questions: dict[str, JevQuestion] = Field(min_length=1)
    model: str = Field(min_length=1)


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
