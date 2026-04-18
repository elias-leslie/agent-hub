"""Schemas for project ownership inventory and overlap coordination."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OwnershipOwnerResponse(BaseModel):
    """A single active/recent owner lane in a project."""

    task_id: str | None = Field(default=None, description="Resolved task id for the lane")
    session_id: str = Field(..., description="Agent Hub session id")
    agent_slug: str | None = Field(default=None, description="Owning agent slug")
    branch: str | None = Field(default=None, description="Current branch for the lane")
    working_dir: str | None = Field(default=None, description="Working directory for the lane")
    session_status: str = Field(..., description="Session lifecycle status")
    workstream_status: str | None = Field(default=None, description="Lane lifecycle status")
    workstream_note: str | None = Field(default=None, description="Optional lifecycle note")
    ownership_kind: str = Field(
        ...,
        description="Derived ownership kind: scoped, unscoped, stale, retired, or superseded",
    )
    scope_paths: list[str] = Field(default_factory=list, description="Normalized touched/scope file paths")
    declared_scope_paths: list[str] = Field(default_factory=list, description="Explicit declared scope paths")
    observed_read_paths: list[str] = Field(default_factory=list, description="Observed recent read paths")
    observed_write_paths: list[str] = Field(default_factory=list, description="Observed recent write paths")
    scope_confidence: str | None = Field(default=None, description="declared | observed_write | observed_read | unknown")
    updated_at: datetime | None = Field(default=None, description="Most recent activity timestamp")
    created_at: datetime = Field(..., description="Session creation timestamp")
    age_minutes: int = Field(..., description="Age in minutes from creation/update")
    is_stale: bool = Field(default=False, description="Whether the lane exceeds stale threshold")


class ActiveSpecialistSessionResponse(BaseModel):
    """A single active non-owner specialist session in a project."""

    session_id: str = Field(..., description="Agent Hub session id")
    agent_slug: str | None = Field(default=None, description="Active specialist agent slug")
    project_id: str = Field(..., description="Project id")
    parent_session_id: str | None = Field(default=None, description="Parent dispatch/session id")
    request_source: str | None = Field(default=None, description="Request source for the session")
    created_at: datetime = Field(..., description="Session creation timestamp")
    age_minutes: int = Field(..., description="Age in minutes from creation/update")


class ProjectOwnershipResponse(BaseModel):
    """Project-scoped ownership inventory used by SummitFlow preflight."""

    project_id: str = Field(..., description="Project id")
    generated_at: datetime = Field(..., description="Snapshot generation time")
    active_owners: list[OwnershipOwnerResponse] = Field(
        default_factory=list,
        description="Active or recently relevant owners for the project",
    )
    active_specialists: list[ActiveSpecialistSessionResponse] = Field(
        default_factory=list,
        description="Active non-owner specialist sessions relevant to duplicate-avoidance",
    )
