"""Core persona API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaUserProfile(BaseModel):
    """Structured user-profile fields the persona can rely on at runtime."""

    user_identity: str | None = Field(default=None, max_length=2000)
    work_context: str | None = Field(default=None, max_length=2000)
    communication_style: str | None = Field(default=None, max_length=1000)
    autonomy_level: str | None = Field(default=None, max_length=500)
    notification_preferences: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, max_length=100)
    working_schedule: str | None = Field(default=None, max_length=1000)
    priorities_values: str | None = Field(default=None, max_length=2000)
    tools_and_integrations: str | None = Field(default=None, max_length=2000)
    boundaries_and_escalation: str | None = Field(default=None, max_length=2000)


class PersonaLimits(BaseModel):
    """Validated autonomous-execution limits."""

    max_turns: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


class PersonaResponse(BaseModel):
    """Full persona representation."""

    id: int
    name: str
    personality: str | None = None
    user_profile: PersonaUserProfile | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str = "en-US-AriaNeural"
    voice_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    execution_state: str = "active"
    avatar_url: str | None = None
    greeting: str | None = None
    onboarding_complete: bool = False
    onboarding_phase: str = "not_started"
    session_reset_mode: str = "off"
    session_reset_hour: int = 9
    session_reset_idle_minutes: int = 120
    limits: PersonaLimits | None = None
    agent_slug: str = "persona"
    version: int = 1
    updated_at: str | None = None


class PersonaUpdate(BaseModel):
    """Partial update for persona fields."""

    name: str | None = Field(default=None, max_length=100)
    personality: str | None = Field(default=None, max_length=50000)
    user_profile: PersonaUserProfile | None = None
    heartbeat_instructions: str | None = Field(default=None, max_length=10000)
    user_context: str | None = Field(default=None, max_length=10000)
    voice_id: str | None = Field(default=None, max_length=200)
    voice_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    execution_state: str | None = Field(default=None, pattern="^(active|paused)$")
    avatar_url: str | None = Field(default=None, max_length=500)
    greeting: str | None = Field(default=None, max_length=2000)
    session_reset_mode: str | None = Field(default=None, pattern="^(off|daily|idle)$")
    session_reset_hour: int | None = Field(default=None, ge=0, le=23)
    session_reset_idle_minutes: int | None = Field(default=None, ge=5, le=1440)
    limits: PersonaLimits | None = None


class PersonaPersonalityResponse(BaseModel):
    """Just the personality text."""

    personality: str | None = None
    version: int = 1


class PersonaPersonalityUpdate(BaseModel):
    """Update the personality document."""

    personality: str = Field(max_length=50000, description="The new personality document (markdown)")
    reason: str = Field(
        default="",
        max_length=500,
        description="Why the personality is being updated (for audit trail)",
    )
