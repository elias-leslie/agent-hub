"""Run definitions accepted by the API and the owner decision used to resume a paused run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .executor_common import load_defaults
from .executors import EXECUTOR_KINDS


class StepTestHooks(BaseModel):
    """Step-level hooks for exercising the engine; honored only while ``workflow_test_hooks_enabled`` is on."""

    model_config = ConfigDict(extra="forbid")

    # End the attempt with a refusal of this category once the model has taken this many turns.
    refuse_after_turn: int | None = Field(None, ge=1)
    refusal_category: str = Field("cyber", min_length=1, max_length=64)


class StepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    instructions: str = Field(min_length=1)
    # The step's ordered model chain is this agent's route (primary, fallbacks, escalation).
    agent_slug: str = Field(min_length=1, max_length=50)
    # Like primary_model_override: run this model first, then the agent's chain.
    model_override: str | None = None
    # Optional narrowing filter over the chain.
    allowed_models: list[str] | None = Field(None, min_length=1)
    # Executor kind; default is chosen from the provider of each attempt's model (policy.executor_for_provider).
    executor: str | None = None
    # Harness tool/prompt level (executor_defaults.json claude_code.levels): "lean" (core tools only, the default)
    # or "full" (the harness's whole built-in set, e.g. for research steps that need subagents or web tools).
    level: str | None = None
    acceptance: list[str] = Field(default_factory=list)
    # Hard cap on attempts for the step; default is one attempt per chain model.
    max_attempts: int | None = Field(None, ge=1)
    workflow_ids: list[str] = Field(default_factory=list)
    test_hooks: StepTestHooks | None = None

    @field_validator("executor")
    @classmethod
    def _known_executor(cls, value: str | None) -> str | None:
        if value is not None and value not in EXECUTOR_KINDS:
            raise ValueError(f"executor must be one of {EXECUTOR_KINDS}")
        return value

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str | None) -> str | None:
        levels = load_defaults()["claude_code"]["levels"]
        if value is not None and value not in levels:
            raise ValueError(f"level must be one of {sorted(levels)}")
        return value


class RunDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    project_id: str = Field(min_length=1, max_length=100)
    repo_path: str | None = None
    base_ref: str = "HEAD"
    task_id: str | None = Field(None, max_length=200)
    request_id: str | None = Field(None, max_length=150)
    policy: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_keys(self) -> RunDefinition:
        keys = [step.key for step in self.steps]
        if len(set(keys)) != len(keys):
            raise ValueError("step keys must be unique")
        return self


class OwnerDecision(BaseModel):
    """How the owner resolves a paused run.

    retry: run the step again (optionally pinned to ``model``, which may be any model);
    skip: mark the step skipped and continue; fail: end the run as failed.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["retry", "skip", "fail"]
    step_key: str | None = None
    model: str | None = None
    note: str | None = Field(None, max_length=2000)
