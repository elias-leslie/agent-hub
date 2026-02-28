"""Schemas for prompt API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PromptCreateRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    description: str | None = None
    is_global: bool = False
    exclude_agents: list[str] = Field(default_factory=list)


class PromptUpdateRequest(BaseModel):
    slug: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str | None = Field(default=None, max_length=200)
    content: str | None = None
    description: str | None = None
    is_global: bool | None = None
    exclude_agents: list[str] | None = None


class PromptResponse(BaseModel):
    id: int
    slug: str
    name: str
    content: str
    description: str | None
    is_global: bool
    exclude_agents: list[str]
    created_at: datetime
    updated_at: datetime


class PromptListResponse(BaseModel):
    prompts: list[PromptResponse]
    total: int


class AgentPromptAssignRequest(BaseModel):
    prompt_slug: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1, max_length=100)
    priority: int = Field(default=0, ge=0)


class AgentPromptUpdateRequest(BaseModel):
    role: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=0)


class AgentPromptResponse(BaseModel):
    prompt: PromptResponse
    role: str
    priority: int


class AgentPromptListResponse(BaseModel):
    assignments: list[AgentPromptResponse]


class RolesResponse(BaseModel):
    roles: list[str]
