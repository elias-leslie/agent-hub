"""Request and response models for the committee roundtable endpoint."""

from typing import Any

from pydantic import BaseModel, Field


class CommitteeSeatConfig(BaseModel):
    key: str
    label: str
    enabled: bool = True
    agent_slug: str
    model_id: str | None = None
    instruction: str | None = None
    weight: float = Field(default=1.0, ge=0.0)


class CommitteeOrchestratorConfig(BaseModel):
    agent_slug: str = "investment-committee"
    model_id: str | None = None
    instruction: str | None = None


class CommitteeConfig(BaseModel):
    orchestrator: CommitteeOrchestratorConfig
    seats: list[CommitteeSeatConfig] = Field(default_factory=list)


class CommitteeRoundtableRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    window_days: int = Field(default=3, ge=1, le=30)
    source_snapshot: dict[str, Any] | str = Field(default_factory=dict)
    project_id: str = Field(default="portfolio-ai")
    agent_slug: str = Field(default="investment-committee")
    symbols: list[str] | None = None
    trace_id: str | None = None
    external_id: str | None = None


class CommitteeRoundtableResponse(BaseModel):
    agent_slug: str
    committee_config: CommitteeConfig
    committee_summary: dict[str, Any] = Field(default_factory=dict)
    calls: list[dict[str, Any]] = Field(default_factory=list)
    votes: list[dict[str, Any]] = Field(default_factory=list)
