"""Agent runner models for Agent Hub client."""

from typing import Any

from pydantic import BaseModel, Field


class AgentProgress(BaseModel):
    """Progress update from agent execution."""

    turn: int = Field(..., description="Current turn number")
    status: str = Field(
        ..., description="Progress status: running, tool_use, thinking, complete, error"
    )
    message: str = Field(..., description="Human-readable progress message")
    topic: str | None = Field(default=None, description="Stable task/lane topic for this progress update")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    thinking: str | None = Field(default=None)

