"""Persona automation API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PersonaImprovementScheduleResponse(BaseModel):
    """Current scheduled persona improvement-loop configuration."""

    job_id: str | None = None
    enabled: bool = False
    schedule_type: str = "every"
    schedule_value: str
    schedule_timezone: str = "UTC"
    cadence_minutes: int = 15
    cadence_label: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0


class PersonaAutomationResponse(BaseModel):
    """Persona-owned scheduled automation summary."""

    id: str
    name: str
    schedule_type: str
    schedule_value: str
    schedule_timezone: str = "UTC"
    payload_type: str = "agent_turn"
    payload_message: str
    payload_title: str | None = None
    delivery: str = "none"
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0
    max_runs: int | None = None
    created_at: str | None = None


class PersonaAutomationCreate(BaseModel):
    """Create one persona-owned scheduled automation."""

    name: str = Field(min_length=1, max_length=200)
    schedule_type: Literal["at", "every", "cron"]
    schedule_value: str = Field(min_length=1, max_length=100)
    schedule_timezone: str = Field(default="UTC", max_length=50)
    payload_type: Literal["agent_turn", "push", "self_honing", "memory_review"] = "agent_turn"
    payload_message: str = Field(min_length=1, max_length=10000)
    payload_title: str | None = Field(default=None, max_length=200)
    delivery: Literal["none", "push", "telegram"] = "none"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_delivery(self) -> PersonaAutomationCreate:
        if self.delivery == "telegram" and self.payload_type != "agent_turn":
            raise ValueError("delivery=telegram requires payload_type=agent_turn")
        return self


class PersonaAutomationUpdate(BaseModel):
    """Patch one persona-owned scheduled automation."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    schedule_type: Literal["at", "every", "cron"] | None = None
    schedule_value: str | None = Field(default=None, min_length=1, max_length=100)
    schedule_timezone: str | None = Field(default=None, max_length=50)
    payload_type: Literal["agent_turn", "push", "self_honing", "memory_review"] | None = None
    payload_message: str | None = Field(default=None, min_length=1, max_length=10000)
    payload_title: str | None = Field(default=None, max_length=200)
    delivery: Literal["none", "push", "telegram"] | None = None
    enabled: bool | None = None


class PersonaAutomationTriggerResponse(BaseModel):
    """Manual trigger result for one persona-owned automation."""

    job: PersonaAutomationResponse
    output: str
    session_id: str | None = None
    triggered_at: str


class PersonaImprovementScheduleUpdate(BaseModel):
    """Update the scheduled persona improvement loop."""

    enabled: bool
    cadence_minutes: int = Field(default=15, ge=15, le=10080)
