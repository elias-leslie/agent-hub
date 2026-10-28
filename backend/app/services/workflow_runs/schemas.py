"""Run definitions accepted by the API and the owner decision used to resume a paused run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .executor_common import load_defaults
from .executors import EXECUTOR_KINDS
from .plan import validate_graph


class StepTestHooks(BaseModel):
    """Step-level hooks for exercising the engine; honored only while ``workflow_test_hooks_enabled`` is on."""

    model_config = ConfigDict(extra="forbid")

    # End the attempt with a refusal of this category once the model has taken this many turns.
    refuse_after_turn: int | None = Field(None, ge=1)
    refusal_category: str = Field("cyber", min_length=1, max_length=64)


class AcceptanceCommand(BaseModel):
    """A shell command the runner runs in the step's worktree after the executor finishes: exit 0 passes."""

    model_config = ConfigDict(extra="forbid")

    cmd: str = Field(min_length=1)
    # Unset, the command runs until it exits.
    timeout_s: int | None = Field(None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _bare_string(cls, value: Any) -> Any:
        return {"cmd": value} if isinstance(value, str) else value


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
    # Harness tool/prompt level (executor_defaults.json claude_code.levels, agent_hub.levels): "lean" (core tools only,
    # the default) or "full" (the harness's whole tool set, e.g. for research steps that need subagents or web tools).
    level: str | None = None
    # The runner, not the agent, decides the step is done: all of these must exit 0 before the checkpoint.
    # A bare string is a command without a time limit.
    acceptance: list[AcceptanceCommand] = Field(default_factory=list)
    # Overrides the agent's thinking level for this step in every executor.
    effort: str | None = None
    # Hard cap on attempts for the step. Unset, the run policy's max_total_attempts applies; this can only lower it.
    max_attempts: int | None = Field(None, ge=1)
    workflow_ids: list[str] = Field(default_factory=list)
    test_hooks: StepTestHooks | None = None
    # Keys of the steps that must complete first; their handoffs are this step's context. Unset, the step depends on
    # the one before it by position. An empty list means it depends on nothing.
    depends_on: list[str] | None = None

    @field_validator("executor")
    @classmethod
    def _known_executor(cls, value: str | None) -> str | None:
        if value is not None and value not in EXECUTOR_KINDS:
            raise ValueError(f"executor must be one of {EXECUTOR_KINDS}")
        return value

    @field_validator("effort")
    @classmethod
    def _known_effort(cls, value: str | None) -> str | None:
        levels = load_defaults()["thinking_levels"]
        if value is not None and value not in levels:
            raise ValueError(f"effort must be one of {levels}")
        return value

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str | None) -> str | None:
        defaults = load_defaults()
        levels = set(defaults["claude_code"]["levels"]) | set(defaults["agent_hub"]["levels"])
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
    # Who started the run: an opaque id (e.g. an Aico session) and an optional label for the coordinating agent.
    launched_by: str | None = Field(None, max_length=200)
    coordinator: str | None = Field(None, max_length=100)
    steps: list[StepDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_plan(self) -> RunDefinition:
        validate_graph((step.key, step.depends_on) for step in self.steps)
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
    # retry only: attempts to allow this step past its cap. The step records who asked and how many; automatic loops
    # never raise a cap.
    extra_attempts: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _extra_only_with_retry(self) -> OwnerDecision:
        if self.extra_attempts is not None and self.action != "retry":
            raise ValueError("extra_attempts only applies to action 'retry'")
        return self


class CancelRequest(BaseModel):
    """Stop a run or one step. The reason is kept with who asked and when."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=2000)


class PlanChange(BaseModel):
    """Who asked for a plan change and why, kept in the run's plan history with the change."""

    model_config = ConfigDict(extra="forbid")

    changed_by: str | None = Field(None, max_length=200)
    reason: str | None = Field(None, max_length=2000)


class AddSteps(PlanChange):
    """Add steps to a run. They take the next positions, in order.

    ``after`` is shorthand for depending on that step: the first added step without its own ``depends_on`` depends on it.
    A step with neither depends on the step before it, as in a new run. ``depends_on`` may name steps added in the
    same call.
    """

    steps: list[StepDefinition] = Field(min_length=1)
    after: str | None = None


class StepRevision(PlanChange):
    """Changes to a pending step. Only the fields sent change; a field sent as null is cleared."""

    instructions: str | None = Field(None, min_length=1)
    agent_slug: str | None = Field(None, min_length=1, max_length=50)
    model_override: str | None = None
    allowed_models: list[str] | None = Field(None, min_length=1)
    executor: str | None = None
    level: str | None = None
    effort: str | None = None
    acceptance: list[AcceptanceCommand] | None = None
    max_attempts: int | None = Field(None, ge=1)
    depends_on: list[str] | None = None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> StepRevision:
        for name in ("instructions", "agent_slug", "acceptance"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        return self

    def changes(self) -> dict[str, Any]:
        """The step fields this revision sets, as plain data (nested models dumped)."""

        out: dict[str, Any] = {}
        for name in self.model_fields_set - set(PlanChange.model_fields):
            value = getattr(self, name)
            out[name] = (
                [c.model_dump() for c in value] if name == "acceptance" and value is not None else value
            )
        return out


class RunRevision(PlanChange):
    """Change a run-level setting of a run that is going on."""

    # Steps that may run at once; a run without a repository stays at 1.
    max_concurrent_steps: int | None = Field(None, ge=1)


class RemoveStep(PlanChange):
    """Remove a pending step. Steps that depend on it must be revised in the same call (``revise``, by step key)."""

    revise: dict[str, StepRevision] = Field(default_factory=dict)
