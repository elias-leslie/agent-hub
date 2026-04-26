"""Unified memory system models — PostgreSQL + pgvector.

Tables:
- memories: All memory types (mandate, guardrail, reference, feedback, journal, continuity)
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.memory_utility_score import calculate_memory_utility_score

from .base import Base


class Memory(Base):
    """Unified memory record — stores mandates, guardrails, references, feedback, journal, continuity."""

    __tablename__ = "memories"

    # Primary key
    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(768), nullable=True)

    # Classification
    memory_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # mandate, guardrail, reference, feedback, journal, continuity
    scope: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="global"
    )  # global, project:<id>, agent:<slug>
    scope_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # project_id when scope=project:<id>
    group_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # logical grouping (e.g. project, session)
    source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # human, agent:<slug>, system:summarizer, chat, voice
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    context_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="reference"
    )
    applicability: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Tier system (determines injection behavior)
    tier: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="3"
    )  # 1=always-inject, 2=conditional, 3=searchable, 4=archive
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    auto_inject: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, server_default="50")

    # Conditional injection
    trigger_task_types: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    trigger_phases: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Usage tracking (drives tier optimization)
    loaded_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    referenced_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    harmful_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )  # active, resolved, archived, deleted
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )  # pending, clean, needs_action, failed
    sensitivity_tier: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="normal"
    )  # normal, personal, confidential
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Demotion tracking
    demoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demotion_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Lifecycle scoring (continuous tier management)
    lifecycle_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifecycle_score_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Graduated retirement
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )

    # Type-specific metadata (JSONB for extensibility)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=True
    )
    # feedback: {component, feedback_type, votes: [], resolution: {}, severity}
    # journal: {entry_type, persona_id}
    # continuity: {session_id, is_session_summary}

    # Reference time (when the memory was valid, not just created)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revisions: Mapped[list[MemoryRevision]] = relationship(
        "MemoryRevision", back_populates="memory", lazy="raise"
    )

    # Indexes are created via raw SQL in the Alembic migration (d3e4f5g6h7i8)
    # because SQLAlchemy doesn't natively handle pgvector index types and
    # partial indexes with JSONB/vector columns.
    __table_args__: tuple = ()

    @property
    def uuid_short(self) -> str:
        """Return first 8 chars of UUID for citation format."""
        return str(self.id).replace("-", "")[:8]

    @property
    def injection_tier(self) -> str:
        """Map numeric tier to string tier name for backward compatibility."""
        return {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}.get(
            self.tier, "reference"
        )

    @injection_tier.setter
    def injection_tier(self, value: str) -> None:
        """Set tier from string name."""
        self.tier = {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}.get(value, 3)

    @property
    def utility_score(self) -> float:
        """Calculate utility score from usage stats."""
        return calculate_memory_utility_score(self.loaded_count, self.referenced_count)


class MemoryRevision(Base):
    """Immutable snapshot of memory state for audit, rollback, and provenance."""

    __tablename__ = "memory_revisions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    memory_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    memory_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    context_kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default="reference")
    applicability: Mapped[dict] = mapped_column("applicability", JSONB, nullable=False, server_default="{}")
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    auto_inject: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    trigger_task_types: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    trigger_phases: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memory: Mapped[Memory | None] = relationship("Memory", back_populates="revisions", lazy="raise")

    __table_args__ = ()


class MemoryReviewRun(Base):
    """Audit row for scheduled memory quality review batches."""

    __tablename__ = "memory_review_runs"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    reviewer_agent_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    reviewer_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    needs_action_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = ()
