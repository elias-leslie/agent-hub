"""Feedback system models: issues, ideas, improvements, and praise from agents."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FeedbackItem(Base):
    """Agent-submitted feedback on infrastructure components.

    Types: friction (fix this), idea (build this), improvement (optimize this),
    praise (preserve this). Agents search before creating to prevent duplicates.
    Duplicate reports become votes on existing items.
    """

    __tablename__ = "feedback_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    component_id: Mapped[str] = mapped_column(String(50), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="open", nullable=False)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # First reporter
    created_by_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    session_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Resolution
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Denormalized for fast sorting
    vote_count: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    # Linked SummitFlow task
    linked_task_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # search_vector is a generated tsvector column — managed by PostgreSQL, not SQLAlchemy
    # Access via raw SQL queries in feedback_storage.py

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    session = relationship("Session", lazy="raise")
    votes = relationship(
        "FeedbackVote", back_populates="feedback_item", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('friction', 'idea', 'improvement', 'praise')",
            name="ck_feedback_items_type",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'wont_fix', 'archived')",
            name="ck_feedback_items_status",
        ),
        Index("idx_feedback_items_component", "component_id"),
        Index("idx_feedback_items_type", "feedback_type"),
        Index("idx_feedback_items_status", "status"),
        Index("idx_feedback_items_project", "project_id"),
        Index("idx_feedback_items_votes", "vote_count"),
        Index("idx_feedback_items_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<FeedbackItem id={self.id!r} type={self.feedback_type!r} component={self.component_id!r} status={self.status!r}>"


class FeedbackVote(Base):
    """Vote on an existing feedback item — one vote per session.

    Agents vote when they encounter the same issue/idea. Optional comment
    provides additional "me too" context.
    """

    __tablename__ = "feedback_votes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    feedback_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("feedback_items.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    feedback_item = relationship("FeedbackItem", back_populates="votes", lazy="raise")
    session = relationship("Session", lazy="raise")

    __table_args__ = (
        UniqueConstraint("feedback_item_id", "session_id", name="uq_feedback_votes_item_session"),
        Index("idx_feedback_votes_item", "feedback_item_id"),
        Index("idx_feedback_votes_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<FeedbackVote id={self.id!r} item={self.feedback_item_id!r}>"
