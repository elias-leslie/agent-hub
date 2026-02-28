"""Persona API — first-class identity management for the concierge persona."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.persona import Persona
from app.services.persona_service import get_or_create_persona

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["persona"])


# --- Schemas ---


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


# --- Helpers ---


def _persona_to_response(persona: Persona, agent_slug: str = "persona") -> PersonaResponse:
    """Convert a Persona ORM object to response schema."""
    return PersonaResponse(
        id=persona.id,
        name=persona.name,
        personality=persona.personality,
        heartbeat_instructions=persona.heartbeat_instructions,
        user_context=persona.user_context,
        voice_id=persona.voice_id,
        voice_enabled=persona.voice_enabled,
        heartbeat_interval_minutes=persona.heartbeat_interval_minutes,
        avatar_url=persona.avatar_url,
        greeting=persona.greeting,
        onboarding_complete=persona.onboarding_complete,
        onboarding_phase=persona.onboarding_phase,
        session_reset_mode=persona.session_reset_mode,
        session_reset_hour=persona.session_reset_hour,
        session_reset_idle_minutes=persona.session_reset_idle_minutes,
        limits=persona.limits,
        agent_slug=agent_slug,
        version=persona.version,
        updated_at=persona.updated_at.isoformat() if persona.updated_at else None,
    )


# --- Endpoints ---


@router.get("", response_model=PersonaResponse)
async def get_persona(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Get the full persona configuration."""
    persona = await get_or_create_persona(db)
    return _persona_to_response(persona)


@router.put("", response_model=PersonaResponse)
async def update_persona(
    update: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaResponse:
    """Update persona fields (partial update — only provided fields are changed)."""
    persona = await get_or_create_persona(db)

    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return _persona_to_response(persona)

    # Shrinkage protection for text documents
    for field in ("user_context", "personality", "heartbeat_instructions"):
        if field in update_data and update_data[field] is not None:
            old_text = getattr(persona, field) or ""
            new_text = update_data[field].strip()
            old_len = len(old_text)
            new_len = len(new_text)
            if old_len > 200 and new_len < (old_len * 0.5):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"REJECTED: New {field} ({new_len} chars) is dramatically shorter "
                        f"than existing ({old_len} chars). This looks like accidental data loss."
                    ),
                )
            # Save backup before overwrite
            backup_field = f"{field}_previous"
            if hasattr(persona, backup_field):
                setattr(persona, backup_field, old_text)
            update_data[field] = new_text

    for field, value in update_data.items():
        setattr(persona, field, value)

    persona.version += 1
    await db.commit()
    await db.refresh(persona)

    logger.info("Persona updated: fields=%s", list(update_data.keys()))
    return _persona_to_response(persona)


@router.post("/reset-onboarding", response_model=PersonaResponse)
async def reset_onboarding(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Reset onboarding so bootstrap instructions are injected on next conversation.

    Clears user_context and resets onboarding_attempts so Jenny starts truly
    fresh — no stale context that could make her act mid-onboarding.
    """
    persona = await get_or_create_persona(db)
    persona.onboarding_complete = False
    persona.onboarding_phase = "not_started"
    persona.onboarding_attempts = 0
    persona.user_context = None
    persona.version += 1
    await db.commit()
    await db.refresh(persona)
    logger.info("Persona onboarding fully reset (phase → not_started, context cleared)")
    return _persona_to_response(persona)


@router.get("/personality", response_model=PersonaPersonalityResponse)
async def get_personality(db: AsyncSession = Depends(get_db)) -> PersonaPersonalityResponse:
    """Get just the personality document (for agent self-read)."""
    persona = await get_or_create_persona(db)
    return PersonaPersonalityResponse(
        personality=persona.personality,
        version=persona.version,
    )


@router.put("/personality", response_model=PersonaPersonalityResponse)
async def update_personality(
    update: PersonaPersonalityUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaPersonalityResponse:
    """Update the personality document (for agent self-modification)."""
    persona = await get_or_create_persona(db)
    persona.personality = update.personality
    persona.version += 1
    await db.commit()
    await db.refresh(persona)

    reason_log = f" reason={update.reason}" if update.reason else ""
    logger.info("Personality updated: version=%d%s", persona.version, reason_log)
    return PersonaPersonalityResponse(
        personality=persona.personality,
        version=persona.version,
    )


# --- Journal Schemas ---


class JournalEntryResponse(BaseModel):
    """A single journal entry."""

    id: int
    entry_date: str
    content: str
    entry_type: str
    created_at: str | None = None


class JournalListResponse(BaseModel):
    """List of journal entries."""

    entries: list[JournalEntryResponse]
    total: int


# --- Journal Endpoints ---


@router.get("/journal", response_model=JournalListResponse)
async def get_journal(
    days_back: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JournalListResponse:
    """Get recent journal entries (read-only for UI)."""
    from datetime import UTC, datetime

    from app.services.memory.repository import get_memory_repository

    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=days_back)
    memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
    )

    return JournalListResponse(
        entries=[
            JournalEntryResponse(
                id=0,  # memories use UUID; id kept for schema compat
                entry_date=(m.valid_at or m.created_at).strftime("%Y-%m-%d"),
                content=m.content,
                entry_type=(m.metadata_ or {}).get("entry_type", "observation"),
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in memories
        ],
        total=len(memories),
    )


# --- Activity Timeline ---

_HOURS_MAP = {"6h": 6, "24h": 24, "7d": 168, "30d": 720, "all": 0}


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


@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="24h", description="Time range: 6h, 24h, 7d, 30d, all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ActivityResponse:
    """Get persona activity timeline — chat + heartbeat sessions interleaved chronologically."""
    from datetime import UTC

    from sqlalchemy import func, select

    from app.models.session import Session, SessionEvent

    # Resolve time range
    hours = _HOURS_MAP.get(time_range, 24)

    # Build query for persona sessions across persona-sandbox + summitflow
    query = select(Session).where(
        Session.agent_slug == "persona",
        Session.project_id.in_(["persona-sandbox", "summitflow"]),
    )
    if hours > 0:
        since = datetime.now(UTC) - timedelta(hours=hours)
        query = query.where(Session.created_at >= since)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)
    sessions = list((await db.execute(query)).scalars().all())

    # Fetch first 3 events per session for preview
    session_ids = [s.id for s in sessions]
    events_by_session: dict[str, list[ActivityEventPreview]] = {}
    if session_ids:
        # Use a lateral/window query: first 3 events per session ordered by sequence
        events_query = (
            select(SessionEvent)
            .where(SessionEvent.session_id.in_(session_ids))
            .order_by(SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence)
        )
        all_events = list((await db.execute(events_query)).scalars().all())

        for evt in all_events:
            sid = evt.session_id
            if sid not in events_by_session:
                events_by_session[sid] = []
            if len(events_by_session[sid]) < 3:
                preview_content = None
                if evt.content:
                    preview_content = evt.content[:200]
                events_by_session[sid].append(
                    ActivityEventPreview(
                        event_type=evt.event_type,
                        tool_name=evt.tool_name,
                        content_preview=preview_content,
                    )
                )

    # Fetch message counts
    if session_ids:
        msg_count_query = (
            select(
                SessionEvent.session_id,
                func.count().label("cnt"),
            )
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type.in_(["user_message", "assistant_message"]),
            )
            .group_by(SessionEvent.session_id)
        )
        msg_counts = {
            row.session_id: row.cnt
            for row in (await db.execute(msg_count_query)).all()
        }
    else:
        msg_counts = {}

    return ActivityResponse(
        sessions=[
            ActivitySession(
                id=s.id,
                session_type=s.session_type or "completion",
                summary_oneliner=s.summary_oneliner,
                status=s.status,
                message_count=msg_counts.get(s.id, 0),
                created_at=s.created_at,
                updated_at=s.updated_at,
                events_preview=events_by_session.get(s.id, []),
            )
            for s in sessions
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
