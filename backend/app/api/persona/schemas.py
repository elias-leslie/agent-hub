"""Pydantic schemas for the persona API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Core persona schemas
# ---------------------------------------------------------------------------


class PersonaResponse(BaseModel):
    """Full persona representation."""

    id: int
    name: str
    personality: str | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str = "en-US-AriaNeural"
    voice_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    avatar_url: str | None = None
    greeting: str | None = None
    onboarding_complete: bool = False
    onboarding_phase: str = "not_started"
    session_reset_mode: str = "off"
    session_reset_hour: int = 9
    session_reset_idle_minutes: int = 120
    limits: dict | None = None
    agent_slug: str = "persona"
    version: int = 1
    updated_at: str | None = None


class PersonaUpdate(BaseModel):
    """Partial update for persona fields."""

    name: str | None = Field(default=None, max_length=100)
    personality: str | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str | None = Field(default=None, max_length=200)
    voice_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    avatar_url: str | None = Field(default=None, max_length=500)
    greeting: str | None = None
    session_reset_mode: str | None = Field(default=None, pattern="^(off|daily|idle)$")
    session_reset_hour: int | None = Field(default=None, ge=0, le=23)
    session_reset_idle_minutes: int | None = Field(default=None, ge=5, le=1440)
    limits: dict | None = None


# ---------------------------------------------------------------------------
# Personality sub-resource schemas
# ---------------------------------------------------------------------------


class PersonaPersonalityResponse(BaseModel):
    """Just the personality text."""

    personality: str | None = None
    version: int = 1


class PersonaPersonalityUpdate(BaseModel):
    """Update the personality document."""

    personality: str = Field(description="The new personality document (markdown)")
    reason: str = Field(
        default="",
        description="Why the personality is being updated (for audit trail)",
    )


# ---------------------------------------------------------------------------
# Journal schemas
# ---------------------------------------------------------------------------


class JournalEntryResponse(BaseModel):
    """A single journal entry (sourced from unified memory system)."""

    entry_date: str
    content: str
    entry_type: str
    created_at: str | None = None


class JournalListResponse(BaseModel):
    """List of journal entries."""

    entries: list[JournalEntryResponse]
    total: int


# ---------------------------------------------------------------------------
# Activity timeline schemas
# ---------------------------------------------------------------------------


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
    created_at: datetime
    updated_at: datetime
    events_preview: list[ActivityEventPreview] = Field(default_factory=list)


class ActivityResponse(BaseModel):
    """Chronological list of persona sessions."""

    sessions: list[ActivitySession]
    total: int
    page: int
    page_size: int
