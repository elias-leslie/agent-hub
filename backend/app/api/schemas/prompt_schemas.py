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
    enabled: bool = True
    boot_eligible: bool = False
    exclude_agents: list[str] = Field(default_factory=list)


class PromptUpdateRequest(BaseModel):
    slug: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str | None = Field(default=None, max_length=200)
    content: str | None = None
    description: str | None = None
    is_global: bool | None = None
    enabled: bool | None = None
    boot_eligible: bool | None = None
    exclude_agents: list[str] | None = None
    change_reason: str | None = None


class PromptResponse(BaseModel):
    id: int
    slug: str
    name: str
    content: str
    description: str | None
    is_global: bool
    enabled: bool
    boot_eligible: bool = False
    exclude_agents: list[str]
    owner_agent_slug: str | None = None
    prompt_type: str | None = None
    deletion_locked: bool = False
    created_at: datetime
    updated_at: datetime


class PromptListResponse(BaseModel):
    prompts: list[PromptResponse]
    total: int


class PromptRevisionResponse(BaseModel):
    id: str
    prompt_id: int | None
    prompt_slug: str
    prompt_name: str
    action: str
    content: str
    description: str | None
    is_global: bool
    enabled: bool
    boot_eligible: bool = False
    exclude_agents: list[str]
    owner_agent_id: int | None
    prompt_type: str | None = None
    deletion_locked: bool = False
    content_hash: str
    changed_by: str | None
    change_reason: str | None
    created_at: datetime


class PromptRevisionListResponse(BaseModel):
    revisions: list[PromptRevisionResponse]
    total: int


class PromptRestoreRequest(BaseModel):
    change_reason: str | None = None


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
