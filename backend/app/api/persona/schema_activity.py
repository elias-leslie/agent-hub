"""Persona activity timeline schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ActivityEventPreview(BaseModel):
    """Minimal event for collapsed session cards."""

    event_type: str
    tool_name: str | None = None
    content_preview: str | None = None


class ActivitySession(BaseModel):
    """A session in the activity timeline."""

    id: str
    session_type: str
    summary_oneliner: str | None = None
    status: str
    message_count: int
    event_count: int | None = None
    child_session_count: int | None = None
    active_child_session_count: int | None = None
    status_source: str = "session"
    status_matches_live: bool = True
    live_status: str | None = None
    live_source: str | None = None
    created_at: datetime
    updated_at: datetime
    events_preview: list[ActivityEventPreview] = Field(default_factory=list)


class ActivityResponse(BaseModel):
    """Chronological list of persona sessions."""

    sessions: list[ActivitySession]
    total: int
    page: int
    page_size: int
