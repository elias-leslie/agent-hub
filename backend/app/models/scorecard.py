"""Component scorecard models for agent feedback system."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ComponentRating(Base):
    """Agent rating for a specific infrastructure component.

    Agents rate the components they interact with on 5 dimensions (1-5 scale).
    Ratings come from 4 sources:
    1. Real-time friction reports (agent-initiated during work)
    2. Hook-based auto-detection (PostToolUse.sh)
    3. End-of-session LLM scorecard (summary workflow)
    4. Manual /rate_it skill (human-initiated)
    """

    __tablename__ = "component_ratings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    component_id: Mapped[str] = mapped_column(String(50), nullable=False)
    reliability: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    clarity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    ergonomics: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    integration: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    documentation: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    session_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session = relationship("Session", lazy="raise")

    __table_args__ = (
        CheckConstraint("reliability BETWEEN 1 AND 5", name="ck_component_ratings_reliability"),
        CheckConstraint("clarity BETWEEN 1 AND 5", name="ck_component_ratings_clarity"),
        CheckConstraint("ergonomics BETWEEN 1 AND 5", name="ck_component_ratings_ergonomics"),
        CheckConstraint("integration BETWEEN 1 AND 5", name="ck_component_ratings_integration"),
        CheckConstraint("documentation BETWEEN 1 AND 5", name="ck_component_ratings_documentation"),
        Index("idx_component_ratings_component", "component_id"),
        Index("idx_component_ratings_session", "session_id"),
        Index("idx_component_ratings_project", "project_id"),
        Index("idx_component_ratings_created", "created_at"),
    )
