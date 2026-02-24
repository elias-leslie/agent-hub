from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ObservationSource(StrEnum):
    CLAUDE_CODE = "claude_code"
    AGENT_HUB_CHAT = "agent_hub_chat"
    SUMMITFLOW_TASK = "summitflow_task"
    AGENTIC = "agentic"
    MANUAL = "manual"


class ObservationType(StrEnum):
    TOOL_USE = "tool_use"
    DECISION = "decision"
    CHANGE = "change"
    LEARNING = "learning"
    ERROR = "error"
    PATTERN = "pattern"
    CONTEXT_SWITCH = "context_switch"
    DECISION_MADE = "decision_made"
    WORKFLOW_OBSERVED = "workflow_observed"


class ObservationRequest(BaseModel):
    source: ObservationSource
    type: ObservationType
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    narrative: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    concepts: list[str] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    prompt_number: int | None = None


class ObservationResponse(BaseModel):
    uuid: str
    stored: bool
    message: str
    episode_name: str
